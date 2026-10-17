"""주제 기반 발견: 탐색 루트들의 노드로 검색해 수집 후보를 등록한다 (DECISIONS D24·D25).

- 탐색 루트(관심사)마다 자기 몫의 검색을 가진다: 사용자가 등록한 관심사 6개, 가지마다 3개.
  루트 노드를 먼저, 그다음 루트에 가깝고 최근 언급이 많은 노드 순서다. 여러 루트에 걸친 노드는
  한 번만 검색한다. 전체 상한(discovery_max_queries)에서 자른다.
- 찾은 URL은 정리해서 후보(discovered_urls)로 등록한다. 이미 등록된 URL은 다시 넣지 않는다.
  실행 한 번에 한 사이트가 차지할 수 있는 후보 수와 전체 후보 수에 상한이 있다.
- 처음 보는 사이트는 검토 대기로 등록한다. 거부·차단된 사이트의 URL은 가져오지 않을 후보로 남긴다.
- 공급자가 준 제목은 본문 없는 문서(헤드라인)로 저장해 바로 분류할 수 있게 한다. 사이트에는 아직
  접근하지 않았다. 본문은 사이트가 허용된 뒤 범용 수집기가 채운다.
- 노드마다 마지막으로 검색한 시각을 기억해 다음에는 그 뒤만 찾는다.
"""

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.collectors.control import emergency_stop_reason
from narrative_radar.collectors.http import RequestStats
from narrative_radar.collectors.sites import ensure_policy
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import (
    DiscoveredUrl,
    InterestProfile,
    Node,
    NodeAlias,
    NodeMention,
    ProfileNode,
    SitePolicy,
)
from narrative_radar.discovery.branch import lineage
from narrative_radar.discovery.expansion import latest_decisions
from narrative_radar.discovery.providers import (
    GDELT_PARSER_VERSION,
    DiscoveredItem,
    DiscoveryProvider,
    QueryRejected,
)
from narrative_radar.discovery.urls import canonical_url, site_of, url_key
from narrative_radar.ingest.health import record_health
from narrative_radar.ingest.runner import RunContext, _get_cursor, _set_cursor
from narrative_radar.ingest.store import DocumentStore
from narrative_radar.schemas.document import DocumentIn
from narrative_radar.schemas.enums import (
    CandidateStatus,
    ContentAccessStatus,
    IngestMode,
    NodeType,
    ProfileNodeStatus,
    ProfileOrigin,
    SitePolicyStatus,
    SourceHealthStatus,
)

ROOT_QUOTA = 6  # 사용자가 등록한 관심사의 검색 몫
BRANCH_QUOTA = 3  # 가지마다
# 공급자 색인이 늦게 반영되는 경우를 대비해 직전 검색과 겹치게 요청한다. 중복은 등록 단계가 거른다.
OVERLAP = timedelta(minutes=15)
MAX_WINDOW = timedelta(days=89)  # GDELT DOC는 최근 3개월만 검색한다
WEB_SOURCE = "web"
CURSOR_KEY = "node_cursors"


@dataclass(frozen=True)
class PlannedQuery:
    node_id: str
    label: str
    profile_id: str
    profile_name: str
    depth: int
    query: str
    priority: int  # 작을수록 먼저


@dataclass
class QueryPlan:
    queries: list[PlannedQuery] = field(default_factory=list)
    unsearchable: list[str] = field(default_factory=list)  # 쓸 수 있는 별칭이 없는 노드


def _ordered_profiles(session: Session) -> list[InterestProfile]:
    """사용자가 등록한 관심사를 먼저, 가지는 얕은 것부터 만든 순서대로."""
    profiles = list(session.scalars(sa.select(InterestProfile)))
    return sorted(
        profiles,
        key=lambda p: (
            p.origin == ProfileOrigin.BRANCH,
            len(lineage(session, p)),
            p.created_at,
            p.profile_id,
        ),
    )


def _admitted_depths(session: Session, profile_id: str) -> dict[str, int]:
    rows = session.execute(
        sa.select(ProfileNode.node_id, ProfileNode.depth)
        .where(ProfileNode.profile_id == profile_id)
        .order_by(ProfileNode.available_at, ProfileNode.decision_id)
    ).all()
    depth_by_node = {node_id: depth or 0 for node_id, depth in rows}
    return {
        node_id: depth_by_node[node_id]
        for node_id, status in latest_decisions(session, profile_id).items()
        if status == ProfileNodeStatus.ADMITTED
    }


def plan_queries(
    session: Session,
    provider: DiscoveryProvider,
    now: datetime,
    max_queries: int,
    root_quota: int = ROOT_QUOTA,
    branch_quota: int = BRANCH_QUOTA,
) -> QueryPlan:
    plan = QueryPlan()
    lanes: list[tuple[InterestProfile, list[tuple[str, int]], int]] = []
    for profile in _ordered_profiles(session):
        depths = _admitted_depths(session, profile.profile_id)
        if not depths:
            continue
        recent = dict(
            session.execute(
                sa.select(NodeMention.node_id, sa.func.count())
                .where(
                    NodeMention.node_id.in_(depths),
                    NodeMention.published_at > now - timedelta(days=7),
                    NodeMention.available_at <= now,
                )
                .group_by(NodeMention.node_id)
            ).all()
        )
        ranked = sorted(depths.items(), key=lambda kv: (kv[1], -recent.get(kv[0], 0), kv[0]))
        quota = branch_quota if profile.origin == ProfileOrigin.BRANCH else root_quota
        lanes.append((profile, ranked, quota))
    if not lanes:
        return plan

    all_nodes = {node_id for _, ranked, _ in lanes for node_id, _ in ranked}
    nodes = {
        n.node_id: n
        for n in session.scalars(
            sa.select(Node).where(
                Node.node_id.in_(all_nodes),
                Node.node_type != NodeType.NARRATIVE,  # 명제 문장은 검색어로 쓰지 않는다
                Node.available_at <= now,
            )
        )
    }
    aliases: dict[str, list[str]] = {}
    for node_id, alias in session.execute(
        sa.select(NodeAlias.node_id, NodeAlias.alias)
        .where(NodeAlias.node_id.in_(nodes), NodeAlias.available_at <= now)
        .order_by(NodeAlias.created_at, NodeAlias.alias_id)
    ):
        aliases.setdefault(node_id, []).append(alias)

    claimed: set[str] = set()
    cursors = [0] * len(lanes)
    left = [quota for _, _, quota in lanes]
    # 루트마다 돌아가며 하나씩: 상한에서 잘려도 모든 탐색 루트가 자기 루트 노드는 검색한다.
    while len(plan.queries) < max_queries and any(left):
        progressed = False
        for i, (profile, ranked, _) in enumerate(lanes):
            while left[i] and cursors[i] < len(ranked) and len(plan.queries) < max_queries:
                node_id, depth = ranked[cursors[i]]
                cursors[i] += 1
                node = nodes.get(node_id)
                if node is None or node_id in claimed:
                    continue
                claimed.add(node_id)
                query = provider.build_query([node.label, *aliases.get(node_id, [])])
                if query is None:
                    plan.unsearchable.append(node.label)
                    continue
                plan.queries.append(
                    PlannedQuery(
                        node_id=node_id,
                        label=node.label,
                        profile_id=profile.profile_id,
                        profile_name=profile.name,
                        depth=depth,
                        query=query,
                        priority=len(plan.queries),
                    )
                )
                left[i] -= 1
                progressed = True
                break
            if cursors[i] >= len(ranked):
                left[i] = 0
        if not progressed:
            break
    return plan


@dataclass
class DiscoveryReport:
    queries: int = 0
    rejected: list[str] = field(default_factory=list)
    items: int = 0
    registered: int = 0
    documents: int = 0
    duplicates: int = 0
    skipped_sites: int = 0  # 거부·차단된 사이트
    capped: int = 0  # 사이트별·전체 상한에 걸림
    invalid: int = 0
    new_sites: int = 0
    stopped: str | None = None


def run_discovery(
    ctx: RunContext,
    provider: DiscoveryProvider,
    run_id: str,
    plan: QueryPlan,
    first_lookback: timedelta = timedelta(hours=24),
    stats: RequestStats | None = None,
    should_stop: Callable[[], str | None] | None = None,
) -> DiscoveryReport:
    """검색마다 결과를 바로 저장한다. 도중에 공급자가 멈춰도(CollectionBlocked) 그때까지 찾은
    후보는 남는다. 긴급 중단 스위치가 켜지면 다음 검색 전에 멈춘다."""
    settings = ctx.settings
    report = DiscoveryReport()
    per_site: Counter[str] = Counter()
    window_start = ctx.clock.now()
    requests_before = stats.requests if stats else 0
    successes_before = stats.successes if stats else 0
    raw = _get_cursor(ctx, CURSOR_KEY)
    cursors: dict[str, str] = dict(raw) if isinstance(raw, dict) else {}

    def stop_reason() -> str | None:
        with ctx.sessions() as session:
            reason = emergency_stop_reason(session)
        if reason is not None:
            return f"emergency stop: {reason}"
        return should_stop() if should_stop else None

    for q in plan.queries:
        if (reason := stop_reason()) is not None:
            report.stopped = reason
            break
        if report.registered >= settings.discovery_max_candidates:
            break
        end = ctx.clock.now()
        last = cursors.get(q.node_id)
        start = datetime.fromisoformat(last) - OVERLAP if last else end - first_lookback
        start = max(start, end - MAX_WINDOW)
        report.queries += 1
        try:
            items = provider.search(q.query, start, end, settings.gdelt_max_records)
        except QueryRejected as e:
            report.rejected.append(f"{q.label}: {e}")
            continue
        with ctx.sessions.begin() as session:
            _register(session, ctx, run_id, provider.name, q, items, per_site, report)
            cursors[q.node_id] = end.isoformat()
            _set_cursor(session, ctx, CURSOR_KEY, dict(cursors))

    with ctx.sessions.begin() as session:
        record_health(
            session,
            ctx.clock,
            ctx.source_adapter_id,
            window_start,
            ctx.clock.now(),
            SourceHealthStatus.OK,
            requests=(stats.requests - requests_before) if stats else report.queries,
            successes=(stats.successes - successes_before) if stats else report.queries,
            documents_listed=report.items,
            documents_fetched=report.documents,
            note=json.dumps(
                {
                    "queries": report.queries,
                    "rejected": len(report.rejected),
                    "registered": report.registered,
                    "duplicates": report.duplicates,
                    "new_sites": report.new_sites,
                    "stopped": report.stopped,
                }
            ),
        )
    return report


def _register(
    session: Session,
    ctx: RunContext,
    run_id: str,
    provider_name: str,
    q: PlannedQuery,
    items: list[DiscoveredItem],
    per_site: Counter[str],
    report: DiscoveryReport,
) -> None:
    settings = ctx.settings
    now = ctx.clock.now()
    late = timedelta(minutes=settings.discovery_late_minutes)
    store = DocumentStore(session, run_id, GDELT_PARSER_VERSION)
    for rank, item in enumerate(items):
        report.items += 1
        canonical = canonical_url(item.url)
        if canonical is None or len(canonical) > 2000:
            report.invalid += 1
            continue
        if session.scalar(
            sa.select(DiscoveredUrl.candidate_id).where(DiscoveredUrl.canonical_url == canonical)
        ):
            report.duplicates += 1
            continue
        site = site_of(canonical)
        if (
            per_site[site] >= settings.discovery_max_per_domain
            or report.registered >= settings.discovery_max_candidates
        ):
            report.capped += 1
            continue
        report.new_sites += session.get(SitePolicy, site) is None
        policy = ensure_policy(session, ctx.clock, site)
        status, reason = CandidateStatus.NEW, None
        if policy.status == SitePolicyStatus.DENIED:
            status, reason = CandidateStatus.SKIPPED, f"site denied: {policy.reason}"
        elif policy.status == SitePolicyStatus.BLOCKED:
            status, reason = CandidateStatus.BLOCKED, f"site blocked: {policy.reason}"
        per_site[site] += 1
        seen_at = min(item.seen_at, now)
        candidate = DiscoveredUrl(
            candidate_id=new_id("cnd", now),
            canonical_url=canonical,
            url=item.url[:2000],
            domain=site,
            title=item.title[:1000],
            language=(item.language or "")[:32] or None,
            source_country=(item.source_country or "")[:64] or None,
            provider=provider_name,
            term=q.query[:300],
            profile_id=q.profile_id,
            priority=q.priority * 100 + min(rank, 99),
            provider_seen_at=seen_at,
            discovered_at=now,
            status=status,
            status_reason=reason,
            attempts=0,
            run_id=run_id,
        )
        if status != CandidateStatus.NEW:
            report.skipped_sites += 1
        else:
            report.registered += 1
            if item.title and len(canonical) <= 1000:
                saved = store.save(
                    DocumentIn(
                        source_adapter_id=WEB_SOURCE,
                        external_id=url_key(canonical),
                        source_url=canonical,
                        title=item.title,
                        body_text=None,
                        published_at=seen_at,
                        observed_at=now,
                        content_access_status=ContentAccessStatus.UNVERIFIED,
                        ingest_mode=IngestMode.BACKFILL
                        if now - seen_at > late
                        else IngestMode.LIVE,
                    ),
                    snapshot_if_existing=False,
                )
                candidate.document_id = saved.document_id
                report.documents += saved.created
        session.add(candidate)
        session.flush()

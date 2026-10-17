"""범용 수집기 실행: 허용된 사이트의 수집 후보를 우선순위대로 가져와 문서로 저장한다 (D25).

- 사이트가 `allowed`인 후보만 가져온다. 사이트별 하루 상한(최근 24시간 요청 수)을 넘으면
  그 사이트는 이번 실행에서 쉰다.
- 사이트 단위 차단기: 접근 거부·수집 금지·접근 제한 신호면 그 사이트만 `blocked`로 두고
  원인·시각을 남긴다. 자동으로 다시 시도하지 않는다. 다른 사이트는 계속한다.
- 일시 오류는 차단과 구분한다. 후보는 다음 실행에서 제한적으로 다시 시도하고, 그 사이트는
  이번 실행에서 쉰다. 한 사이트에서 연달아 일정 횟수를 넘으면 차단기가 그 사이트를 멈춘다.
- 서로 다른 사이트 여러 곳에서 연달아 일시 오류가 나면 우리 쪽 네트워크 문제로 보고 이번
  실행을 멈춘다 (사이트들을 잘못 차단하지 않도록).
- 헤드라인 문서가 있으면 본문을 채운다(내용이 바뀌어 다시 분류된다). 본문을 찾지 못하면
  헤드라인만 둔다.
- 모든 요청 결과를 fetch_logs에 남긴다. 긴급 중단 스위치가 켜지면 다음 요청 전에 멈춘다.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.collectors.control import emergency_stop_reason
from narrative_radar.collectors.sites import ensure_policy, set_policy
from narrative_radar.collectors.web import FetchResult, RequestLog, SafeWebFetcher
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import DiscoveredUrl, FetchLog, SitePolicy
from narrative_radar.discovery.urls import url_key
from narrative_radar.ingest.health import record_health
from narrative_radar.ingest.runner import RunContext
from narrative_radar.ingest.store import DocumentStore
from narrative_radar.schemas.document import DocumentIn
from narrative_radar.schemas.enums import (
    CandidateStatus,
    ContentAccessStatus,
    FetchOutcome,
    IngestMode,
    SitePolicyStatus,
    SourceHealthStatus,
)

WEB_SOURCE = "web"
WEB_PARSER_VERSION = "web.v1"
MIN_TEXT_CHARS = 200  # 이보다 짧으면 본문을 찾지 못한 것으로 본다
NETWORK_STOP_AFTER = 5  # 서로 다른 사이트 이만큼에서 연달아 일시 오류면 이번 실행을 멈춘다
BREAKER = "breaker"


@dataclass
class WebReport:
    attempted: int = 0
    fetched: int = 0
    upgraded: int = 0  # 헤드라인 → 본문
    created: int = 0
    headline_only: int = 0
    transient: int = 0
    rejected: int = 0
    skipped: int = 0
    requests: int = 0
    blocked_sites: list[str] = field(default_factory=list)
    stopped: str | None = None


def site_usage(session: Session, site: str, now: datetime) -> int:
    """최근 24시간 동안 그 사이트에 보낸 페이지 요청 수 (robots.txt 제외)."""
    return (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(FetchLog)
            .where(
                FetchLog.domain == site,
                FetchLog.at > now - timedelta(days=1),
                FetchLog.outcome != FetchOutcome.SKIPPED,
                ~FetchLog.url.endswith("/robots.txt"),
            )
        )
        or 0
    )


def due_candidates(session: Session, limit: int) -> list[DiscoveredUrl]:
    return list(
        session.scalars(
            sa.select(DiscoveredUrl)
            .join(SitePolicy, SitePolicy.domain == DiscoveredUrl.domain)
            .where(
                DiscoveredUrl.status == CandidateStatus.NEW,
                SitePolicy.status == SitePolicyStatus.ALLOWED,
            )
            .order_by(DiscoveredUrl.priority, DiscoveredUrl.discovered_at)
            .limit(limit)
        )
    )


def collect_web(
    ctx: RunContext,
    fetcher: SafeWebFetcher,
    run_id: str,
    limit: int,
    should_stop: Callable[[], str | None] | None = None,
) -> WebReport:
    report = WebReport()
    window_start = ctx.clock.now()
    resting: set[str] = set()  # 이번 실행에서 쉬는 사이트
    transient_streak: list[str] = []
    with ctx.sessions() as session:
        todo = [
            (c.candidate_id, c.canonical_url, c.domain) for c in due_candidates(session, limit * 4)
        ]

    def site_allowed(site: str) -> str | None:
        with ctx.sessions.begin() as session:
            policy = ensure_policy(session, ctx.clock, site)  # 처음 보는 사이트는 검토 대기로 등록
            return None if policy.status == SitePolicyStatus.ALLOWED else f"site is {policy.status}"

    for candidate_id, url, site in todo:
        if report.attempted >= limit:
            break
        with ctx.sessions() as session:
            reason = emergency_stop_reason(session)
        reason = f"emergency stop: {reason}" if reason else (should_stop() if should_stop else None)
        if reason is not None:
            report.stopped = reason
            break
        if site in resting:
            report.skipped += 1
            continue
        with ctx.sessions() as session:
            policy = session.get(SitePolicy, site)
            if policy is None or policy.status != SitePolicyStatus.ALLOWED:
                report.skipped += 1  # 이번 실행 도중 차단됐다
                continue
            if site_usage(session, site, ctx.clock.now()) >= policy.daily_limit:
                resting.add(site)
                report.skipped += 1
                continue

        logs: list[RequestLog] = []
        result = fetcher.fetch(url, site_allowed, logs.append)
        report.attempted += 1
        report.requests += len(logs)
        with ctx.sessions.begin() as session:
            _write_logs(session, ctx, run_id, logs)
            _apply(session, ctx, run_id, candidate_id, site, result, report)

        if result.outcome == FetchOutcome.TRANSIENT:
            resting.add(result.site)
            transient_streak.append(result.site)
            if len(set(transient_streak)) >= NETWORK_STOP_AFTER:
                report.stopped = (
                    f"transient errors at {NETWORK_STOP_AFTER} different sites in a row; "
                    "our network may be down"
                )
                break
        elif result.outcome != FetchOutcome.SKIPPED:
            transient_streak.clear()

    with ctx.sessions.begin() as session:
        record_health(
            session,
            ctx.clock,
            ctx.source_adapter_id,
            window_start,
            ctx.clock.now(),
            SourceHealthStatus.DEGRADED
            if report.blocked_sites or report.stopped
            else SourceHealthStatus.OK,
            requests=report.requests,
            successes=report.fetched,
            failures=report.transient + report.rejected + len(report.blocked_sites),
            documents_listed=report.attempted,
            documents_fetched=report.fetched,
            note=json.dumps(
                {
                    "upgraded": report.upgraded,
                    "created": report.created,
                    "headline_only": report.headline_only,
                    "blocked_sites": report.blocked_sites,
                    "stopped": report.stopped,
                }
            ),
        )
    return report


def _write_logs(session: Session, ctx: RunContext, run_id: str, logs: list[RequestLog]) -> None:
    now = ctx.clock.now()
    for entry in logs:
        session.add(
            FetchLog(
                log_id=new_id("flg", now),
                domain=entry.site,
                url=entry.url[:2000],
                outcome=entry.outcome,
                status_code=entry.status_code,
                detail=entry.detail[:500] or None,
                at=now,
                run_id=run_id,
            )
        )
        if entry.robots and entry.outcome == FetchOutcome.OK:
            ensure_policy(session, ctx.clock, entry.site).robots_checked_at = now
    session.flush()


def _apply(
    session: Session,
    ctx: RunContext,
    run_id: str,
    candidate_id: str,
    site: str,
    result: FetchResult,
    report: WebReport,
) -> None:
    settings = ctx.settings
    now = ctx.clock.now()
    cand = session.get_one(DiscoveredUrl, candidate_id)
    cand.attempts += 1
    cand.last_attempt_at = now
    cand.status_reason = result.detail[:500] or None
    policy = ensure_policy(session, ctx.clock, result.site)

    if result.outcome == FetchOutcome.OK:
        policy.consecutive_transient = 0
        cand.status = CandidateStatus.FETCHED
        report.fetched += 1
        _store_page(session, ctx, run_id, cand, result, report)
    elif result.outcome == FetchOutcome.BLOCKED:
        set_policy(
            session,
            ctx.clock,
            result.site,
            SitePolicyStatus.BLOCKED,
            f"{result.detail} ({result.url})"[:500],
            decided_by=BREAKER,
        )
        cand.status = CandidateStatus.BLOCKED
        report.blocked_sites.append(result.site)
    elif result.outcome == FetchOutcome.TRANSIENT:
        report.transient += 1
        policy.consecutive_transient += 1
        if policy.consecutive_transient >= settings.web_breaker_transient_limit:
            set_policy(
                session,
                ctx.clock,
                result.site,
                SitePolicyStatus.BLOCKED,
                f"{policy.consecutive_transient} transient errors in a row: {result.detail}"[:500],
                decided_by=BREAKER,
            )
            report.blocked_sites.append(result.site)
        too_many = cand.attempts > settings.web_transient_retries
        cand.status = CandidateStatus.FAILED if too_many else CandidateStatus.NEW
    elif result.outcome == FetchOutcome.REJECTED:
        report.rejected += 1
        cand.status = CandidateStatus.FAILED
    else:  # SKIPPED: 허용되지 않은 사이트로 가는 리다이렉트. 그 사이트가 허용되면 다시 시도한다
        report.skipped += 1
        too_many = cand.attempts > settings.web_transient_retries
        cand.status = CandidateStatus.SKIPPED if too_many else CandidateStatus.NEW
    policy.updated_at = now


def _store_page(
    session: Session,
    ctx: RunContext,
    run_id: str,
    cand: DiscoveredUrl,
    result: FetchResult,
    report: WebReport,
) -> None:
    page = result.page
    assert page is not None
    now = ctx.clock.now()
    text = page.text if len(page.text) >= MIN_TEXT_CHARS else None
    title = cand.title or page.title or ""
    if text is None:
        report.headline_only += 1
        cand.status_reason = "no main text found"
    if (not title and text is None) or len(cand.canonical_url) > 1000:
        return
    published = page.published_at or cand.provider_seen_at or now
    late = timedelta(minutes=ctx.settings.discovery_late_minutes)
    saved = DocumentStore(session, run_id, WEB_PARSER_VERSION).save(
        DocumentIn(
            source_adapter_id=WEB_SOURCE,
            external_id=url_key(cand.canonical_url),
            source_url=cand.canonical_url,
            title=title,
            body_text=text,
            published_at=published,
            observed_at=now,
            content_access_status=ContentAccessStatus.UNVERIFIED,
            ingest_mode=IngestMode.BACKFILL if now - published > late else IngestMode.LIVE,
        ),
        snapshot_if_existing=False,
    )
    cand.document_id = saved.document_id
    report.created += saved.created
    report.upgraded += saved.content_changed

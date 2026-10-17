"""수집 실행기. 수집 허용 조건을 확인하고, 수집기 결과를 저장하고, 문제가 생기면 그 즉시 소스를
멈춘 상태로 기록한다 (DATA_POLICY 5, 7).
"""

import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from narrative_radar.collectors.author import AuthorHasher
from narrative_radar.collectors.bluesky import (
    BlueskyMetrics,
    DeleteAuthor,
    DeletePost,
    EnvelopeError,
    JetstreamHandler,
    JetstreamStream,
    SavePost,
)
from narrative_radar.collectors.gate import auto_stop, can_collect, get_adapter
from narrative_radar.collectors.guard import BlockGuard, CollectionBlocked, TripKind
from narrative_radar.collectors.hackernews import HackerNewsCollector
from narrative_radar.core.clock import Clock
from narrative_radar.core.config import Settings
from narrative_radar.db.models import (
    Document,
    DocumentMetricSnapshot,
    InterestProfile,
    Node,
    NodeAlias,
    NodeMention,
    PipelineRun,
    ProfileNode,
)
from narrative_radar.ingest.health import record_health
from narrative_radar.ingest.runs import finish_run, start_run
from narrative_radar.ingest.store import DocumentStore
from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas.enums import (
    NodeType,
    ProfileNodeStatus,
    RunKind,
    RunStatus,
    SourceHealthStatus,
)

# 새 글의 지표를 다시 읽는 시점 (DECISIONS D2)
REVISIT_OFFSETS = (
    timedelta(minutes=10),
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(hours=24),
)


class CollectionNotAllowed(RuntimeError):
    pass


@dataclass
class RunContext:
    settings: Settings
    sessions: sessionmaker[Session]
    clock: Clock
    source_adapter_id: str

    @property
    def revisit_offsets(self) -> tuple[timedelta, ...]:
        return tuple(timedelta(minutes=m) for m in sorted(self.settings.revisit_offsets_minutes))

    def require_allowed(self) -> AuthorHasher:
        with self.sessions() as session:
            decision = can_collect(self.settings, get_adapter(session, self.source_adapter_id))
        if not decision.allowed:
            raise CollectionNotAllowed(decision.reason)
        assert self.settings.author_hash_salt is not None
        return AuthorHasher(self.settings.author_hash_salt.get_secret_value())

    def guard(self) -> BlockGuard:
        """멈추는 순간 별도 세션으로 소스 상태를 바로 기록하는 guard."""

        def on_trip(kind: TripKind, reason: str) -> None:
            with self.sessions.begin() as session:
                auto_stop(session, self.source_adapter_id, kind, reason, self.clock)
                now = self.clock.now()
                record_health(
                    session,
                    self.clock,
                    self.source_adapter_id,
                    now,
                    now,
                    SourceHealthStatus.BLOCKED
                    if kind == TripKind.BLOCKED
                    else SourceHealthStatus.DOWN,
                    note=reason,
                )

        return BlockGuard(on_trip=on_trip)

    @contextmanager
    def run(self, kind: RunKind, params: dict[str, object]) -> Iterator[str]:
        with self.sessions.begin() as session:
            run_id = start_run(session, self.clock, kind, params=params).run_id
        status, error = RunStatus.SUCCEEDED, None
        try:
            yield run_id
        except CollectionBlocked as e:
            status, error = RunStatus.ABORTED, str(e)
            raise
        except BaseException as e:
            status, error = RunStatus.FAILED, f"{type(e).__name__}: {e}"
            raise
        finally:
            with self.sessions.begin() as session:
                run = session.get_one(PipelineRun, run_id)
                finish_run(run, self.clock.now(), status, error)


def profile_terms(
    session: Session,
    now: datetime | None = None,
    limit: int | None = None,
    ascii_only: bool = False,
) -> list[str]:
    """관심사 그래프들에 포함된 노드의 별칭을 검색어로 쓴다 (트리가 자라면 검색어도 자란다).

    순서: 관심사 루트 → 최근 7일 언급이 많은 노드 → 루트에 가까운 노드. limit에서 자른다.
    내러티브 노드(명제 문장)는 검색어로 쓰지 않는다. 같은 표기는 한 번만 쓴다 (DECISIONS D23).
    """
    from narrative_radar.discovery.expansion import latest_decisions

    depth_of: dict[str, int] = {}
    for profile_id in session.scalars(sa.select(InterestProfile.profile_id)):
        latest = session.execute(
            sa.select(ProfileNode.node_id, ProfileNode.depth)
            .where(ProfileNode.profile_id == profile_id)
            .order_by(ProfileNode.available_at, ProfileNode.decision_id)
        ).all()
        depth_by_node = {node_id: depth for node_id, depth in latest}
        for node_id, status in latest_decisions(session, profile_id).items():
            if status == ProfileNodeStatus.ADMITTED:
                d = depth_by_node.get(node_id) or 0
                depth_of[node_id] = min(depth_of.get(node_id, d), d)
    if not depth_of:
        return []
    narratives = set(
        session.scalars(
            sa.select(Node.node_id).where(
                Node.node_id.in_(depth_of), Node.node_type == NodeType.NARRATIVE
            )
        )
    )
    recent: dict[str, int] = {}
    if now is not None:
        recent = dict(
            session.execute(
                sa.select(NodeMention.node_id, sa.func.count())
                .where(
                    NodeMention.node_id.in_(depth_of),
                    NodeMention.published_at > now - timedelta(days=7),
                    NodeMention.available_at <= now,
                )
                .group_by(NodeMention.node_id)
            ).all()
        )
    ranked = sorted(
        (n for n in depth_of if n not in narratives),
        key=lambda n: (depth_of[n] != 0, -recent.get(n, 0), depth_of[n], n),
    )
    aliases: dict[str, list[str]] = {}
    for node_id, alias in session.execute(
        sa.select(NodeAlias.node_id, NodeAlias.alias)
        .where(NodeAlias.node_id.in_(ranked))
        .order_by(NodeAlias.alias)
    ):
        aliases.setdefault(node_id, []).append(alias)
    terms: dict[str, str] = {}  # 정규화 표기 → 원래 표기
    for node_id in ranked:
        for alias in aliases.get(node_id, []):
            if ascii_only and not alias.isascii():
                continue
            terms.setdefault(normalize_text(alias), alias)
            if limit is not None and len(terms) >= limit:
                return list(terms.values())
    return list(terms.values())


def due_revisits(
    session: Session,
    source_adapter_id: str,
    now: datetime,
    limit: int = 50,
    offsets: tuple[timedelta, ...] = REVISIT_OFFSETS,
) -> list[str]:
    """지표를 다시 읽을 때가 된 글 (기본: 관측 후 10분·1시간·6시간·24시간)."""
    horizon = now - offsets[-1] - timedelta(hours=1)
    last_snapshot = (
        sa.select(
            DocumentMetricSnapshot.document_id,
            sa.func.max(DocumentMetricSnapshot.observed_at).label("last_at"),
        )
        .group_by(DocumentMetricSnapshot.document_id)
        .subquery()
    )
    rows = session.execute(
        sa.select(Document.external_id, Document.observed_at, last_snapshot.c.last_at)
        .outerjoin(last_snapshot, last_snapshot.c.document_id == Document.document_id)
        .where(
            Document.source_adapter_id == source_adapter_id,
            Document.deleted_observed_at.is_(None),
            Document.observed_at >= horizon,
        )
        .order_by(Document.observed_at)
    ).all()

    due: list[str] = []
    for external_id, observed_at, last_at in rows:
        for offset in offsets:
            target = observed_at + offset
            if target <= now and (last_at is None or last_at < target):
                due.append(external_id)
                break
        if len(due) >= limit:
            break
    return due


def _get_cursor(ctx: RunContext, key: str) -> object:
    with ctx.sessions() as session:
        return (get_adapter(session, ctx.source_adapter_id).config or {}).get(key)


def _set_cursor(session: Session, ctx: RunContext, key: str, value: object) -> None:
    adapter = get_adapter(session, ctx.source_adapter_id)
    adapter.config = {**(adapter.config or {}), key: value}


# --- Hacker News -------------------------------------------------------------------------


@dataclass
class CycleReport:
    documents: int
    created: int
    revisits: int
    deleted: int


def hackernews_cycle(ctx: RunContext, collector: HackerNewsCollector, run_id: str) -> CycleReport:
    # 네트워크 요청을 하는 동안에는 DB 쓰기 트랜잭션을 잡지 않는다 (다른 수집기와 SQLite 공유).
    window_start = ctx.clock.now()
    requests_before = collector.client.stats.requests
    successes_before = collector.client.stats.successes
    raw = _get_cursor(ctx, "since")
    since = datetime.fromisoformat(raw) if isinstance(raw, str) else None

    result = collector.poll(since)
    created = 0
    with ctx.sessions.begin() as session:
        store = DocumentStore(session, run_id, collector.parser_version)
        for doc in result.documents:
            created += store.save(doc, snapshot_if_existing=False).created
        if result.newest_published_at is not None:
            _set_cursor(session, ctx, "since", result.newest_published_at.isoformat())

    with ctx.sessions() as session:
        due = due_revisits(
            session, ctx.source_adapter_id, ctx.clock.now(), offsets=ctx.revisit_offsets
        )
    revisits = [collector.revisit(external_id) for external_id in due]

    deleted = 0
    with ctx.sessions.begin() as session:
        store = DocumentStore(session, run_id, collector.parser_version)
        deleted = _apply_revisits(store, ctx.source_adapter_id, revisits)
        record_health(
            session,
            ctx.clock,
            ctx.source_adapter_id,
            window_start,
            ctx.clock.now(),
            SourceHealthStatus.OK,
            requests=collector.client.stats.requests - requests_before,
            successes=collector.client.stats.successes - successes_before,
            documents_listed=len(result.documents),
            documents_fetched=created,
            note=json.dumps(
                {"queries": result.queries, "revisits": len(revisits), "deleted": deleted}
            ),
        )
    return CycleReport(len(result.documents), created, len(revisits), deleted)


def _apply_revisits(store: DocumentStore, source_adapter_id: str, revisits: list) -> int:  # type: ignore[type-arg]
    deleted = 0
    for r in revisits:
        if r.deleted:
            deleted += store.mark_deleted(source_adapter_id, r.external_id, r.observed_at)
        elif r.metrics is not None:
            store.add_metrics(source_adapter_id, r.external_id, r.observed_at, r.metrics)
    return deleted


# --- Bluesky ------------------------------------------------------------------------------


@dataclass
class StreamReport:
    events: int
    matched: int
    deleted: int
    stopped_reason: str | None


def consume_bluesky(
    ctx: RunContext,
    stream: JetstreamStream,
    handler: JetstreamHandler,
    run_id: str,
    flush_every: timedelta = timedelta(seconds=30),
    should_stop: Callable[[], bool] = lambda: False,
) -> StreamReport:
    """스트림을 읽어 저장한다. 문제가 생기면 stream이 CollectionBlocked를 던진다."""
    raw = _get_cursor(ctx, "cursor_time_us")
    cursor = raw if isinstance(raw, int) else None
    pending: list[SavePost | DeletePost | DeleteAuthor] = []
    window_start = ctx.clock.now()
    last_flush = time.monotonic()
    deleted = 0
    stopped_reason: str | None = None

    def flush(status: SourceHealthStatus = SourceHealthStatus.OK) -> None:
        nonlocal pending, window_start, deleted
        now = ctx.clock.now()
        with ctx.sessions.begin() as session:
            store = DocumentStore(session, run_id, "bluesky.v1")
            saved = 0
            for action in pending:
                if isinstance(action, SavePost):
                    saved += store.save(action.document).created
                elif isinstance(action, DeletePost):
                    deleted += store.mark_deleted(ctx.source_adapter_id, action.external_id, now)
                else:
                    deleted += store.mark_author_deleted(
                        ctx.source_adapter_id, action.author_hash, now
                    )
            if handler.last_time_us is not None:
                _set_cursor(session, ctx, "cursor_time_us", handler.last_time_us)
            record_health(
                session,
                ctx.clock,
                ctx.source_adapter_id,
                window_start,
                now,
                status,
                documents_listed=handler.stats.posts_seen,
                documents_fetched=saved,
                note=json.dumps(
                    handler.stats.__dict__
                    | {"bytes": stream.bytes_received, "reconnects": stream.reconnects}
                ),
            )
        pending = []
        window_start = now

    try:
        for event in stream.events(cursor):
            try:
                pending.extend(handler.handle(event))
            except EnvelopeError as e:
                stream.guard.trip(TripKind.ERROR, f"parse failed: {e}")
                raise CollectionBlocked(str(e)) from e
            if time.monotonic() - last_flush >= flush_every.total_seconds():
                flush()
                last_flush = time.monotonic()
            if should_stop():
                break
    except CollectionBlocked as e:
        stopped_reason = str(e)
        raise
    finally:
        # 멈추더라도 그때까지 받은 것은 저장한다. 멈춘 구간은 정상으로 기록하지 않는다.
        if pending or handler.stats.events:
            flush(SourceHealthStatus.DEGRADED if stream.guard.tripped else SourceHealthStatus.OK)
    return StreamReport(handler.stats.events, handler.stats.posts_matched, deleted, stopped_reason)


def revisit_bluesky(ctx: RunContext, metrics: BlueskyMetrics, run_id: str) -> CycleReport:
    with ctx.sessions() as session:
        due = due_revisits(
            session, ctx.source_adapter_id, ctx.clock.now(), limit=100, offsets=ctx.revisit_offsets
        )
    revisits = metrics.revisit_many(due)
    with ctx.sessions.begin() as session:
        deleted = _apply_revisits(
            DocumentStore(session, run_id, "bluesky.v1"), ctx.source_adapter_id, revisits
        )
    return CycleReport(0, 0, len(revisits), deleted)

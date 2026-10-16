"""수집 실행기 통합 테스트. 네트워크 대신 형식만 맞춘 예시 응답을 쓴다 (DECISIONS D0 예외)."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from typer.testing import CliRunner
from websockets.exceptions import ConnectionClosedError

from narrative_radar.collectors.author import AuthorHasher
from narrative_radar.collectors.bluesky import JetstreamHandler, JetstreamStream
from narrative_radar.collectors.gate import set_status
from narrative_radar.collectors.guard import CollectionBlocked
from narrative_radar.collectors.hackernews import HackerNewsCollector
from narrative_radar.collectors.http import PoliteClient
from narrative_radar.collectors.rate_limit import MinIntervalLimiter
from narrative_radar.core.config import Settings
from narrative_radar.db.models import (
    Document,
    DocumentMetricSnapshot,
    PipelineRun,
    RawDocument,
    SourceAdapter,
    SourceHealth,
)
from narrative_radar.db.seed import seed_defaults
from narrative_radar.ingest.report import source_report
from narrative_radar.ingest.runner import (
    CollectionNotAllowed,
    RunContext,
    consume_bluesky,
    due_revisits,
    hackernews_cycle,
    profile_terms,
)
from narrative_radar.schemas.enums import (
    IngestMode,
    RunKind,
    RunStatus,
    SourceAccessStatus,
    SourceHealthStatus,
)

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
SALT = "s" * 32


@pytest.fixture
def ctx(session_factory, clock):
    with session_factory.begin() as s:
        seed_defaults(s, clock)
        for sid in ("hackernews", "bluesky_jetstream"):
            set_status(s, sid, SourceAccessStatus.LIVE, "test", clock, live_enabled=True)
    settings = Settings(live_collection_enabled=True, author_hash_salt=SALT)
    return lambda sid: RunContext(settings, session_factory, clock, sid)


def hn_api(hits, items=None):
    items = items or {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "hn.algolia.com":
            return httpx.Response(200, json={"hits": hits, "nbPages": 1})
        item_id = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
        return httpx.Response(200, content=json.dumps(items.get(item_id)).encode())

    return handler


def hn_collector(ctx, handler, clock):
    client = PoliteClient(
        "NarrativeRadar/test",
        limiter=MinIntervalLimiter(0),
        guard=ctx.guard(),
        transport=httpx.MockTransport(handler),
    )
    return HackerNewsCollector(
        client, AuthorHasher(SALT), clock, ["NVIDIA"], live_since=clock.now() - timedelta(hours=1)
    )


STORY = {
    "objectID": "1",
    "_tags": ["story"],
    "created_at_i": int((NOW - timedelta(minutes=3)).timestamp()),
    "title": "Example NVIDIA story",
    "url": "https://example.com/a",
    "author": "alice",
    "points": 5,
    "num_comments": 1,
}


def test_profile_terms_come_from_root_aliases(session_factory, ctx):
    with session_factory() as s:
        terms = profile_terms(s)
    assert {"NVIDIA", "NVDA", "엔비디아"} <= set(terms)


def test_collection_refused_when_not_allowed(session_factory, clock):
    with session_factory.begin() as s:
        seed_defaults(s, clock)
    off = RunContext(Settings(author_hash_salt=SALT), session_factory, clock, "hackernews")
    with pytest.raises(CollectionNotAllowed):
        off.require_allowed()


def test_hackernews_cycles_store_documents_revisit_and_record_health(session_factory, ctx, clock):
    c = ctx("hackernews")
    items = {"1": {"id": 1, "type": "story", "score": 20, "descendants": 4}}
    collector = hn_collector(c, hn_api([STORY], items), clock)
    with c.run(RunKind.COLLECT, {}) as run_id:
        first = hackernews_cycle(c, collector, run_id)
        clock.advance(timedelta(minutes=11))
        second = hackernews_cycle(c, collector, run_id)

    assert (first.created, second.created) == (1, 0)
    assert second.revisits == 1
    with session_factory() as s:
        doc = s.scalars(sa.select(Document)).one()
        assert doc.ingest_mode == IngestMode.LIVE
        counts = s.scalars(
            sa.select(DocumentMetricSnapshot.upvote_count).order_by(
                DocumentMetricSnapshot.observed_at
            )
        ).all()
        assert counts == [5, 20]  # 처음 본 값과 10분 뒤 다시 읽은 값
        health = s.scalars(sa.select(SourceHealth)).all()
        assert [h.status for h in health] == [SourceHealthStatus.OK, SourceHealthStatus.OK]
        cursor = s.get(SourceAdapter, "hackernews").config["since"]
        assert datetime.fromisoformat(cursor) == datetime.fromtimestamp(
            STORY["created_at_i"], tz=UTC
        )
        run = s.scalars(sa.select(PipelineRun).where(PipelineRun.kind == RunKind.COLLECT)).one()
        assert run.status == RunStatus.SUCCEEDED


def test_hackernews_revisit_finds_deleted_item_and_removes_text(session_factory, ctx, clock):
    c = ctx("hackernews")
    items = {"1": {"id": 1, "deleted": True}}
    collector = hn_collector(c, hn_api([STORY], items), clock)
    with c.run(RunKind.COLLECT, {}) as run_id:
        hackernews_cycle(c, collector, run_id)
        clock.advance(timedelta(minutes=11))
        report = hackernews_cycle(c, collector, run_id)
    assert report.deleted == 1
    with session_factory() as s:
        doc = s.scalars(sa.select(Document)).one()
        assert doc.deleted_observed_at is not None
        assert s.get(RawDocument, doc.document_id) is None


def test_hackernews_problem_stops_source_immediately_and_marks_run(session_factory, ctx, clock):
    c = ctx("hackernews")

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(503)

    collector = hn_collector(c, handler, clock)
    with pytest.raises(CollectionBlocked), c.run(RunKind.COLLECT, {}) as run_id:
        hackernews_cycle(c, collector, run_id)

    with session_factory() as s:
        adapter = s.get(SourceAdapter, "hackernews")
        assert adapter.access_status == SourceAccessStatus.STOPPED
        assert adapter.live_enabled is False
        assert "503" in adapter.status_reason
        health = s.scalars(sa.select(SourceHealth)).all()
        assert [h.status for h in health] == [SourceHealthStatus.DOWN]
        run = s.scalars(sa.select(PipelineRun).where(PipelineRun.kind == RunKind.COLLECT)).one()
        assert run.status == RunStatus.ABORTED
    # 멈춘 뒤에는 수집 허용 조건을 통과하지 못한다
    with pytest.raises(CollectionNotAllowed):
        c.require_allowed()


class FakeWebSocket:
    def __init__(self, messages):
        self.messages = list(messages)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def recv(self):
        if self.messages:
            return self.messages.pop(0)
        raise ConnectionClosedError(None, None)


def bsky_event(text, rkey, op="create"):
    commit = {"operation": op, "collection": "app.bsky.feed.post", "rkey": rkey}
    if op != "delete":
        commit["record"] = {"text": text}
    return json.dumps(
        {
            "did": "did:plc:example",
            "time_us": int(NOW.timestamp() * 1_000_000),
            "kind": "commit",
            "commit": commit,
        }
    )


def test_bluesky_stream_saves_matches_applies_deletes_and_stops_on_drop(
    session_factory, ctx, clock
):
    c = ctx("bluesky_jetstream")
    ws = FakeWebSocket(
        [
            bsky_event("example NVIDIA post", "a1"),
            bsky_event("unrelated post", "a2"),
            bsky_event("another nvda post", "a3"),
            bsky_event("", "a3", op="delete"),
        ]
    )
    stream = JetstreamStream(
        "NarrativeRadar/test", c.guard(), connect=lambda url, **kw: ws, reconnect_delays=()
    )
    handler = JetstreamHandler(AuthorHasher(SALT), clock, ["NVIDIA", "NVDA"])
    with pytest.raises(CollectionBlocked), c.run(RunKind.COLLECT, {}) as run_id:
        consume_bluesky(c, stream, handler, run_id)

    with session_factory() as s:
        docs = {d.external_id.rsplit("/", 1)[-1]: d for d in s.scalars(sa.select(Document))}
        assert set(docs) == {"a1", "a3"}
        assert docs["a1"].deleted_observed_at is None
        assert docs["a3"].deleted_observed_at is not None
        adapter = s.get(SourceAdapter, "bluesky_jetstream")
        assert adapter.access_status == SourceAccessStatus.STOPPED
        assert adapter.config["cursor_time_us"] == int(NOW.timestamp() * 1_000_000)
        statuses = [h.status for h in s.scalars(sa.select(SourceHealth))]
        # 멈춘 순간의 기록(down)과, 멈춘 구간까지의 저장 기록(degraded)
        assert statuses == [SourceHealthStatus.DOWN, SourceHealthStatus.DEGRADED]


def test_due_revisits_follow_offsets(session_factory, ctx, clock):
    c = ctx("hackernews")
    collector = hn_collector(
        c, hn_api([STORY], {"1": {"id": 1, "type": "story", "score": 1}}), clock
    )
    with c.run(RunKind.COLLECT, {}) as run_id:
        hackernews_cycle(c, collector, run_id)
    with session_factory() as s:
        assert due_revisits(s, "hackernews", clock.now() + timedelta(minutes=5)) == []
        assert due_revisits(s, "hackernews", clock.now() + timedelta(minutes=10)) == ["1"]
        assert due_revisits(s, "hackernews", clock.now() + timedelta(days=3)) == []


def test_report_summarizes_collection(session_factory, ctx, clock):
    c = ctx("hackernews")
    collector = hn_collector(c, hn_api([STORY]), clock)
    with c.run(RunKind.COLLECT, {}) as run_id:
        hackernews_cycle(c, collector, run_id)
    with session_factory() as s:
        reports = {r.source_adapter_id: r for r in source_report(s, clock.now())}
    hn = reports["hackernews"]
    assert (hn.documents_in_window, hn.live, hn.backfill, hn.snapshots) == (1, 1, 0, 1)
    assert hn.median_delay_seconds == pytest.approx(180)
    assert hn.health_by_status == {"ok": 1}
    assert reports["dcinside_stockus"].documents_in_window == 0


def test_cli_collect_refuses_without_permission(db_url, session_factory, clock, monkeypatch):
    with session_factory.begin() as s:
        seed_defaults(s, clock)
    monkeypatch.setenv("NR_DB_PATH", db_url.removeprefix("sqlite:///"))
    from narrative_radar.cli import app
    from narrative_radar.core.config import get_settings

    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["collect", "hackernews"])
        assert result.exit_code == 2
        assert "수집할 수 없습니다" in result.output
    finally:
        get_settings.cache_clear()

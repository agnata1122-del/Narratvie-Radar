"""주제 기반 발견 (DECISIONS D24·D25).

GDELT 응답은 공개된 DOC 2.0 API 형식(artlist JSON)을 따라 직접 작성한 형식 확인용 예시다.
URL은 예시용 도메인(example.com 등)만 쓴다 (DECISIONS D0 예외).
"""

from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest
import sqlalchemy as sa
from graphkit import HBM, NV, SKH
from typer.testing import CliRunner

from narrative_radar.collectors.control import set_emergency_stop
from narrative_radar.collectors.gate import set_status
from narrative_radar.collectors.guard import CollectionBlocked
from narrative_radar.collectors.http import PoliteClient
from narrative_radar.collectors.rate_limit import MinIntervalLimiter
from narrative_radar.core.config import Settings
from narrative_radar.db.models import (
    DiscoveredUrl,
    Document,
    RawDocument,
    SitePolicy,
    SourceAdapter,
)
from narrative_radar.discovery.branch import create_branch
from narrative_radar.discovery.providers import (
    BraveSearchProvider,
    GdeltProvider,
    ProviderDisabled,
    gdelt_query,
)
from narrative_radar.discovery.run import plan_queries, run_discovery
from narrative_radar.discovery.urls import canonical_url, site_of, url_key
from narrative_radar.ingest.runner import CollectionNotAllowed, RunContext
from narrative_radar.schemas.enums import (
    CandidateStatus,
    ContentAccessStatus,
    IngestMode,
    RunKind,
    SitePolicyStatus,
    SourceAccessStatus,
)

SALT = "s" * 32


def test_canonical_url_drops_tracking_and_noise():
    a = canonical_url("HTTPS://WWW.Example.com:443/news/a?utm_source=x&b=2&a=1&fbclid=z#top")
    assert a == "https://example.com/news/a?a=1&b=2"
    assert canonical_url("https://www.example.com/news/a?b=2&a=1") == a
    assert canonical_url("http://example.com:8080") == "http://example.com:8080/"
    assert canonical_url("ftp://example.com/x") is None
    assert canonical_url("https://user:pw@example.com/x") is None
    assert canonical_url("not a url") is None
    assert site_of(a) == "example.com"
    assert site_of("https://news.example.org/x") == "news.example.org"
    assert url_key(a) == url_key(a) and len(url_key(a)) == 34


def test_gdelt_query_uses_english_aliases_only():
    q = gdelt_query(["NVIDIA", "엔비디아", "NVDA", "NVIDIA Corporation", "nvidia", "AI"])
    assert q == '(NVIDIA OR NVDA OR "NVIDIA Corporation")'
    assert gdelt_query(["HBM"]) == "HBM"
    assert gdelt_query(["SK hynix"]) == '"SK hynix"'
    assert gdelt_query(["엔비디아", "AI"]) is None


def _tree(g):
    g.confirm(HBM, NV)
    g.confirm(SKH, HBM, words=("third wording sample", "fourth wording different entirely"))
    g.build()


def test_each_exploration_root_gets_its_own_share_of_searches(g, clock):
    _tree(g)
    create_branch(g.session, clock, g.profile, g.node("TECH:hbm").node_id)
    provider = GdeltProvider(None)  # type: ignore[arg-type]
    plan = plan_queries(g.session, provider, clock.now(), max_queries=20)
    got = [(q.profile_name, q.label) for q in plan.queries]
    # 루트마다 자기 루트 노드를 먼저, 여러 루트에 걸친 노드는 한 번만
    assert got == [("NVIDIA Research", "NVIDIA"), ("HBM", "HBM"), ("NVIDIA Research", "SK hynix")]
    assert [q.priority for q in plan.queries] == [0, 1, 2]
    # 상한이 작아도 모든 탐색 루트가 자기 루트는 검색한다
    tight = plan_queries(g.session, provider, clock.now(), max_queries=2)
    assert [q.label for q in tight.queries] == ["NVIDIA", "HBM"]


# --- GDELT 형식 예시 ------------------------------------------------------------------------


def article(url, title, seen, domain="example.com"):
    return {
        "url": url,
        "url_mobile": "",
        "title": title,
        "seendate": seen.strftime("%Y%m%dT%H%M%SZ"),
        "socialimage": "",
        "domain": domain,
        "language": "English",
        "sourcecountry": "United States",
    }


class FakeGdelt:
    """검색식별로 정해 둔 응답을 돌려주고 요청을 기록한다."""

    def __init__(self, by_query, default=None):
        self.by_query = by_query
        self.default = default or (lambda: httpx.Response(200, json={}))
        self.requests: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        self.requests.append(params)
        make = self.by_query.get(params["query"], self.default)
        return make()


@pytest.fixture
def setup(g, clock, session_factory):
    _tree(g)
    g.session.commit()
    with session_factory.begin() as s:
        set_status(s, "gdelt", SourceAccessStatus.LIVE, "test", clock, live_enabled=True)

    def make(fake, **overrides):
        settings = Settings(live_collection_enabled=True, author_hash_salt=SALT, **overrides)
        ctx = RunContext(settings, session_factory, clock, "gdelt")
        client = PoliteClient(
            "NarrativeRadar/test",
            limiter=MinIntervalLimiter(0),
            guard=ctx.guard(),
            transport=httpx.MockTransport(fake),
        )
        provider = GdeltProvider(client)
        with session_factory() as s:
            plan = plan_queries(s, provider, clock.now(), settings.discovery_max_queries)
        return ctx, provider, client, plan

    return make


NV_Q = '(NVIDIA OR NVDA OR "NVIDIA Corporation")'


def test_discovery_registers_candidates_sites_and_headlines(setup, clock, session_factory):
    seen = clock.now() - timedelta(minutes=20)
    fake = FakeGdelt(
        {
            NV_Q: lambda: httpx.Response(
                200,
                json={
                    "articles": [
                        article(
                            "https://www.example.com/a?utm_source=x", "Example headline A", seen
                        ),
                        article("https://example.com/a", "Example headline A", seen),
                        article(
                            "https://gall.dcinside.com/x", "Example denied", seen, "dcinside.com"
                        ),
                        article(
                            "https://news.example.org/b",
                            "Example headline B",
                            clock.now() - timedelta(hours=5),
                            "news.example.org",
                        ),
                    ]
                },
            ),
        }
    )
    ctx, provider, client, plan = setup(fake)
    with ctx.run(RunKind.COLLECT, {}) as run_id:
        r = run_discovery(ctx, provider, run_id, plan, stats=client.stats)

    assert (r.queries, r.items, r.registered, r.duplicates, r.skipped_sites) == (3, 4, 2, 1, 1)
    assert (r.documents, r.new_sites) == (2, 3)
    with session_factory() as s:
        cands = {c.domain: c for c in s.scalars(sa.select(DiscoveredUrl))}
        assert cands["example.com"].canonical_url == "https://example.com/a"
        assert cands["example.com"].status == CandidateStatus.NEW
        assert cands["example.com"].term == NV_Q
        assert cands["gall.dcinside.com"].status == CandidateStatus.SKIPPED
        assert cands["gall.dcinside.com"].document_id is None
        sites = {p.domain: p.status for p in s.scalars(sa.select(SitePolicy))}
        assert sites == {
            "example.com": SitePolicyStatus.PENDING_REVIEW,
            "news.example.org": SitePolicyStatus.PENDING_REVIEW,
            "gall.dcinside.com": SitePolicyStatus.DENIED,
        }
        docs = {d.title: d for d in s.scalars(sa.select(Document))}
        a, b = docs["Example headline A"], docs["Example headline B"]
        assert a.source_adapter_id == "web" and a.external_id == url_key(a.source_url)
        assert a.content_access_status == ContentAccessStatus.UNVERIFIED
        assert s.get(RawDocument, a.document_id) is None  # 사이트에는 아직 접근하지 않았다
        assert a.published_at == seen.replace(microsecond=0)
        assert (a.ingest_mode, b.ingest_mode) == (IngestMode.LIVE, IngestMode.BACKFILL)
        cursors = s.get(SourceAdapter, "gdelt").config["node_cursors"]
        assert len(cursors) == 3

    # 다음 실행은 기억한 시각(조금 겹치게) 이후만 찾고, 같은 URL은 다시 넣지 않는다
    clock.advance(timedelta(hours=1))
    with ctx.run(RunKind.COLLECT, {}) as run_id:
        again = run_discovery(ctx, provider, run_id, plan, stats=client.stats)
    assert (again.registered, again.duplicates) == (0, 4)
    last = fake.requests[-1]
    assert last["startdatetime"] == (clock.now() - timedelta(minutes=75)).strftime("%Y%m%d%H%M%S")
    assert last["mode"] == "artlist" and last["format"] == "json"


def test_one_site_cannot_take_over_a_run(setup, clock, session_factory):
    seen = clock.now()
    many = [article(f"https://example.com/{i}", f"Example {i}", seen) for i in range(5)]
    fake = FakeGdelt({NV_Q: lambda: httpx.Response(200, json={"articles": many})})
    ctx, provider, client, plan = setup(fake, discovery_max_per_domain=2)
    with ctx.run(RunKind.COLLECT, {}) as run_id:
        r = run_discovery(ctx, provider, run_id, plan)
    assert (r.registered, r.capped) == (2, 3)


def test_rejected_query_skips_only_that_search(setup, clock, session_factory):
    ok = [article("https://example.com/x", "Example X", clock.now())]
    fake = FakeGdelt(
        {
            NV_Q: lambda: httpx.Response(
                200,
                text="The specified phrase is too short.",
                headers={"content-type": "text/plain"},
            ),
            "HBM": lambda: httpx.Response(200, json={"articles": ok}),
        }
    )
    ctx, provider, client, plan = setup(fake)
    with ctx.run(RunKind.COLLECT, {}) as run_id:
        r = run_discovery(ctx, provider, run_id, plan)
    assert r.rejected == ["NVIDIA: The specified phrase is too short."]
    assert r.registered == 1
    with session_factory() as s:
        assert s.get(SourceAdapter, "gdelt").access_status == SourceAccessStatus.LIVE


def test_gdelt_problem_stops_only_the_gdelt_source(setup, clock, session_factory):
    ok = [article("https://example.com/x", "Example X", clock.now())]
    fake = FakeGdelt(
        {
            NV_Q: lambda: httpx.Response(200, json={"articles": ok}),
            "HBM": lambda: httpx.Response(429, text="Please limit requests"),
        }
    )
    ctx, provider, client, plan = setup(fake)
    with pytest.raises(CollectionBlocked), ctx.run(RunKind.COLLECT, {}) as run_id:
        run_discovery(ctx, provider, run_id, plan)
    with session_factory() as s:
        gdelt = s.get(SourceAdapter, "gdelt")
        assert gdelt.access_status == SourceAccessStatus.BLOCKED and not gdelt.live_enabled
        # 다른 소스는 그대로, 멈추기 전에 찾은 후보는 남는다
        assert s.get(SourceAdapter, "hackernews").access_status == SourceAccessStatus.NOT_AUTHORIZED
        assert s.scalar(sa.select(sa.func.count()).select_from(DiscoveredUrl)) == 1
    # 같은 실행 안에서도 다시 요청하지 않는다
    with pytest.raises(CollectionBlocked):
        provider.search("HBM", clock.now(), clock.now(), 10)


def test_unexpected_response_shape_stops_instead_of_guessing(setup, clock, session_factory):
    bad = {"articles": [{"title": "no url"}]}
    fake = FakeGdelt({NV_Q: lambda: httpx.Response(200, json=bad)})
    ctx, provider, client, plan = setup(fake)
    with (
        pytest.raises(CollectionBlocked, match="article shape"),
        ctx.run(RunKind.COLLECT, {}) as run_id,
    ):
        run_discovery(ctx, provider, run_id, plan)
    with session_factory() as s:
        assert s.get(SourceAdapter, "gdelt").access_status == SourceAccessStatus.STOPPED


def test_emergency_stop_blocks_new_runs_and_halts_running_ones(setup, clock, session_factory):
    fake = FakeGdelt({})
    ctx, provider, client, plan = setup(fake)
    with session_factory.begin() as s:
        set_emergency_stop(s, clock, True, "owner check")
    with pytest.raises(CollectionNotAllowed, match="emergency stop"):
        ctx.require_allowed()
    with ctx.run(RunKind.COLLECT, {}) as run_id:
        r = run_discovery(ctx, provider, run_id, plan)
    assert r.queries == 0 and r.stopped == "emergency stop: owner check"
    assert fake.requests == []

    with session_factory.begin() as s:
        set_emergency_stop(s, clock, False, "resumed")
    ctx.require_allowed()


def test_brave_is_an_interface_only():
    brave = BraveSearchProvider()
    assert not brave.enabled
    assert brave.build_query(["NVIDIA", "SK hynix"]) == 'NVIDIA OR "SK hynix"'
    with pytest.raises(ProviderDisabled):
        brave.search("x", None, None, 10)  # type: ignore[arg-type]


def test_cli_plan_and_emergency_switch(db_url, g, clock, monkeypatch):
    _tree(g)
    g.session.commit()
    monkeypatch.setenv("NR_DB_PATH", db_url.removeprefix("sqlite:///"))
    from narrative_radar.cli import app
    from narrative_radar.core.config import get_settings

    get_settings.cache_clear()
    try:
        runner = CliRunner()
        plan = runner.invoke(app, ["discover", "plan"])
        assert plan.exit_code == 0, plan.output
        assert NV_Q in plan.output and "SK hynix" in plan.output
        assert runner.invoke(app, ["emergency", "stop", "--reason", "test"]).exit_code == 0
        assert "ON (test)" in runner.invoke(app, ["emergency", "status"]).output
        refused = runner.invoke(app, ["discover", "gdelt"])
        assert refused.exit_code == 2 and "emergency stop" in refused.output
        assert runner.invoke(app, ["emergency", "resume", "--reason", "ok"]).exit_code == 0
        assert "off" in runner.invoke(app, ["emergency", "status"]).output
    finally:
        get_settings.cache_clear()

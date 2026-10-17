"""범용 수집기와 사이트 단위 차단기 (DECISIONS D25).

발견 → 사이트 허용 → 가져오기 → 헤드라인 본문 채우기 흐름을 형식 확인용 예시로 확인한다.
HTML·GDELT 응답은 직접 작성했고 예시용 도메인만 쓴다 (DECISIONS D0 예외).
"""

from datetime import timedelta

import httpx
import pytest
import sqlalchemy as sa
from graphkit import HBM, NV
from typer.testing import CliRunner

from narrative_radar.collectors.control import set_emergency_stop
from narrative_radar.collectors.gate import set_status
from narrative_radar.collectors.sites import ensure_policy, set_policy
from narrative_radar.collectors.web import SafeWebFetcher, SiteIntervals
from narrative_radar.core.config import Settings
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import (
    DiscoveredUrl,
    Document,
    FetchLog,
    RawDocument,
    SitePolicy,
)
from narrative_radar.discovery.urls import canonical_url, site_of, url_key
from narrative_radar.ingest.runner import RunContext
from narrative_radar.ingest.runs import start_run
from narrative_radar.ingest.store import DocumentStore
from narrative_radar.ingest.web import collect_web
from narrative_radar.schemas.document import DocumentIn
from narrative_radar.schemas.enums import (
    CandidateStatus,
    ContentAccessStatus,
    FetchOutcome,
    IngestMode,
    RunKind,
    SitePolicyStatus,
    SourceAccessStatus,
)

SALT = "s" * 32
TEXT = " ".join(["This example paragraph has enough words to count as article text."] * 5)


def page(title="Example headline"):
    body = (
        f"<html><head><title>{title}</title></head>"
        f"<body><article><p>{TEXT}</p></article></body></html>"
    )
    return httpx.Response(200, text=body, headers={"content-type": "text/html"})


@pytest.fixture
def env(g, clock, session_factory):
    g.confirm(HBM, NV)
    g.build()
    g.session.commit()
    with session_factory.begin() as s:
        set_status(s, "web", SourceAccessStatus.LIVE, "test", clock, live_enabled=True)
        run_id = start_run(s, clock, RunKind.COLLECT).run_id

    def add(url, title="Example headline", priority=0, headline=True):
        canonical = canonical_url(url)
        with session_factory.begin() as s:
            ensure_policy(s, clock, site_of(canonical))
            doc_id = None
            if headline:
                doc_id = (
                    DocumentStore(s, run_id, "gdelt.doc.v1")
                    .save(
                        DocumentIn(
                            source_adapter_id="web",
                            external_id=url_key(canonical),
                            source_url=canonical,
                            title=title,
                            published_at=clock.now() - timedelta(minutes=30),
                            observed_at=clock.now(),
                            content_access_status=ContentAccessStatus.UNVERIFIED,
                            ingest_mode=IngestMode.LIVE,
                        )
                    )
                    .document_id
                )
            s.add(
                DiscoveredUrl(
                    candidate_id=new_id("cnd", clock.now()),
                    canonical_url=canonical,
                    url=url,
                    domain=site_of(canonical),
                    title=title,
                    provider="gdelt",
                    term="HBM",
                    priority=priority,
                    provider_seen_at=clock.now() - timedelta(minutes=30),
                    discovered_at=clock.now(),
                    status=CandidateStatus.NEW,
                    attempts=0,
                    document_id=doc_id,
                    run_id=run_id,
                )
            )

    def allow(site, **kw):
        with session_factory.begin() as s:
            set_policy(s, clock, site, SitePolicyStatus.ALLOWED, "test", "owner", **kw)

    def collect(routes, limit=10, **overrides):
        settings = Settings(live_collection_enabled=True, author_hash_salt=SALT, **overrides)
        ctx = RunContext(settings, session_factory, clock, "web")
        ctx.require_allowed()

        def handler(request):
            make = routes.get(f"{request.url.host}{request.url.path}")
            if make is None:
                return httpx.Response(404)
            return make(request) if callable(make) else make

        fetcher = SafeWebFetcher(
            "NarrativeRadar/test",
            SiteIntervals(0),
            resolver=lambda host: ["93.184.216.34"],
            transport=httpx.MockTransport(handler),
        )
        with ctx.run(RunKind.COLLECT, {}) as rid:
            return collect_web(ctx, fetcher, rid, limit)

    return add, allow, collect


def _cand(s, url):
    return s.scalars(sa.select(DiscoveredUrl).where(DiscoveredUrl.url == url)).one()


def test_allowed_sites_are_fetched_and_a_refusal_blocks_only_that_site(env, session_factory):
    add, allow, collect = env
    add("https://example.com/a", priority=0)
    add("https://example.com/b", priority=1)
    add("https://example.com/c", priority=2)
    add("https://news.example.org/x", priority=3)  # 허용 전이라 가져오지 않는다
    add("https://example.net/y", priority=4)
    allow("example.com")
    allow("example.net")
    r = collect(
        {
            "example.com/a": page(),
            "example.com/b": httpx.Response(403),
            "example.com/c": page(),
            "example.net/y": page(),
        }
    )
    assert (r.attempted, r.fetched, r.upgraded, r.blocked_sites) == (3, 2, 2, ["example.com"])
    with session_factory() as s:
        a = _cand(s, "https://example.com/a")
        assert a.status == CandidateStatus.FETCHED
        raw = s.get(RawDocument, a.document_id)
        assert raw is not None and raw.body_text == TEXT
        doc = s.get(Document, a.document_id)
        assert doc.processed_at is None  # 본문이 채워졌으니 다시 분류한다
        assert _cand(s, "https://example.com/b").status == CandidateStatus.BLOCKED
        assert (
            _cand(s, "https://example.com/c").status == CandidateStatus.NEW
        )  # 차단 뒤로는 요청 안 함
        assert _cand(s, "https://news.example.org/x").status == CandidateStatus.NEW
        assert (
            _cand(s, "https://example.net/y").status == CandidateStatus.FETCHED
        )  # 다른 사이트는 계속
        policy = s.get(SitePolicy, "example.com")
        assert policy.status == SitePolicyStatus.BLOCKED and policy.decided_by == "breaker"
        assert "HTTP 403" in policy.reason and policy.blocked_at is not None
        assert policy.robots_checked_at is not None
        outcomes = s.scalars(
            sa.select(FetchLog.outcome).where(FetchLog.url == "https://example.com/b")
        ).all()
        assert outcomes == [FetchOutcome.BLOCKED]

    # 차단된 사이트는 다음 실행에서도 자동으로 다시 시도하지 않는다
    again = collect({"example.com/c": page()})
    assert again.attempted == 0


def test_temporary_errors_retry_a_little_then_the_breaker_trips(env, session_factory, clock):
    add, allow, collect = env
    add("https://example.com/a")
    allow("example.com")
    down = {"example.com/a": httpx.Response(503)}
    first = collect(down, web_breaker_transient_limit=3)
    assert (first.transient, first.blocked_sites) == (1, [])
    with session_factory() as s:
        cand = _cand(s, "https://example.com/a")
        assert (cand.status, cand.attempts) == (CandidateStatus.NEW, 1)
        assert s.get(SitePolicy, "example.com").consecutive_transient == 1
    collect(down, web_breaker_transient_limit=3)
    with session_factory() as s:
        assert s.get(SitePolicy, "example.com").status == SitePolicyStatus.ALLOWED
    third = collect(down, web_breaker_transient_limit=3)
    assert third.blocked_sites == ["example.com"]
    with session_factory() as s:
        cand = _cand(s, "https://example.com/a")
        assert (cand.status, cand.attempts) == (CandidateStatus.FAILED, 3)  # 재시도 2번까지
        assert "3 transient errors" in s.get(SitePolicy, "example.com").reason


def test_success_resets_the_temporary_error_count(env, session_factory):
    add, allow, collect = env
    add("https://example.com/a", priority=0)
    add("https://example.com/b", priority=1)
    allow("example.com")
    collect({"example.com/a": httpx.Response(503)})
    collect({"example.com/a": page(), "example.com/b": page()})
    with session_factory() as s:
        assert s.get(SitePolicy, "example.com").consecutive_transient == 0


def test_many_sites_failing_together_stops_the_run_without_blocking_them(env, session_factory):
    add, allow, collect = env
    for i in range(7):
        add(f"https://site{i}.example.com/a", priority=i)
        allow(f"site{i}.example.com")

    def offline(request):
        raise httpx.ConnectError("network unreachable", request=request)

    routes = {f"site{i}.example.com/robots.txt": offline for i in range(7)}
    r = collect(routes)
    assert r.attempted == 5 and "network may be down" in r.stopped
    with session_factory() as s:
        blocked = s.scalars(
            sa.select(SitePolicy).where(SitePolicy.status == SitePolicyStatus.BLOCKED)
        ).all()
        assert blocked == []


def test_daily_limit_per_site(env, session_factory):
    add, allow, collect = env
    for i in range(3):
        add(f"https://example.com/{i}", priority=i)
    allow("example.com", daily_limit=2)
    routes = {f"example.com/{i}": page() for i in range(3)}
    r = collect(routes)
    assert (r.fetched, r.skipped) == (2, 1)
    with session_factory() as s:
        assert _cand(s, "https://example.com/2").status == CandidateStatus.NEW


def test_redirect_to_an_unreviewed_site_waits_for_review(env, session_factory):
    add, allow, collect = env
    add("https://example.com/a")
    allow("example.com")
    r = collect(
        {"example.com/a": httpx.Response(301, headers={"location": "https://other.example.org/a"})}
    )
    assert r.skipped == 1
    with session_factory() as s:
        cand = _cand(s, "https://example.com/a")
        assert cand.status == CandidateStatus.NEW and "other.example.org" in cand.status_reason
        assert s.get(SitePolicy, "other.example.org").status == SitePolicyStatus.PENDING_REVIEW


def test_page_without_main_text_keeps_the_headline(env, session_factory):
    add, allow, collect = env
    add("https://example.com/a")
    allow("example.com")
    thin = httpx.Response(
        200, text="<html><body><p>short</p></body></html>", headers={"content-type": "text/html"}
    )
    r = collect({"example.com/a": thin})
    assert (r.fetched, r.headline_only, r.upgraded) == (1, 1, 0)
    with session_factory() as s:
        cand = _cand(s, "https://example.com/a")
        assert cand.status_reason == "no main text found"
        assert s.get(RawDocument, cand.document_id) is None


def test_emergency_stop_halts_before_any_request(env, session_factory, clock):
    add, allow, collect = env
    add("https://example.com/a")
    allow("example.com")
    with session_factory.begin() as s:
        set_emergency_stop(s, clock, True, "owner check")
    settings = Settings(live_collection_enabled=True, author_hash_salt=SALT)
    with pytest.raises(Exception, match="emergency stop"):
        RunContext(settings, session_factory, clock, "web").require_allowed()


def test_denylisted_sites_cannot_be_allowed(db_url, env, monkeypatch):
    monkeypatch.setenv("NR_DB_PATH", db_url.removeprefix("sqlite:///"))
    from narrative_radar.cli import app
    from narrative_radar.core.config import get_settings

    get_settings.cache_clear()
    try:
        runner = CliRunner()
        refused = runner.invoke(app, ["sites", "allow", "gall.dcinside.com", "--reason", "x"])
        assert refused.exit_code == 2 and "denylist" in refused.output
        ok = runner.invoke(app, ["sites", "allow", "example.com", "--reason", "terms checked"])
        assert ok.exit_code == 0, ok.output
        listing = runner.invoke(app, ["sites", "list"]).output
        assert "allowed" in listing and "example.com" in listing
        assert runner.invoke(app, ["sites", "reset", "example.com", "--reason", "x"]).exit_code == 1
    finally:
        get_settings.cache_clear()

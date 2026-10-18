"""`nr collect …`: 수집 실행 명령. 수집 허용 조건(DATA_POLICY 7)을 통과해야 실행된다."""

import time

import typer

from narrative_radar.core.config import get_settings

collect_app = typer.Typer(help="수집 실행 (docs/DATA_POLICY.md)", no_args_is_help=True)


def _context(source_adapter_id: str):  # type: ignore[no-untyped-def]
    from narrative_radar.core.clock import SystemClock
    from narrative_radar.db.session import make_engine, make_session_factory
    from narrative_radar.ingest.runner import RunContext

    settings = get_settings()
    return RunContext(
        settings=settings,
        sessions=make_session_factory(make_engine(settings.database_url)),
        clock=SystemClock(),
        source_adapter_id=source_adapter_id,
    )


def _require_allowed(ctx):  # type: ignore[no-untyped-def]
    from narrative_radar.ingest.runner import CollectionNotAllowed

    try:
        return ctx.require_allowed()
    except CollectionNotAllowed as e:
        typer.echo(f"수집할 수 없습니다: {e}")
        typer.echo("docs/DATA_POLICY.md 7번 규칙과 `nr sources list`를 확인하세요.")
        raise typer.Exit(code=2) from e


def _stopped(e: Exception) -> None:
    typer.echo(f"수집을 멈췄습니다: {e}")
    typer.echo("원인을 확인한 뒤 `nr sources reset <소스> --reason ...` → `nr sources enable`")
    raise typer.Exit(code=1) from e


@collect_app.command("hackernews")
def collect_hackernews(
    loop: bool = typer.Option(False, help="계속 반복한다"),
    interval: int = typer.Option(120, min=60, help="반복 간격(초). 최소 60"),
    max_cycles: int | None = typer.Option(None, help="이 횟수만큼 돌고 끝낸다"),
    lookback_minutes: int = typer.Option(60, help="처음 실행할 때 거슬러 올라갈 시간(분)"),
) -> None:
    """Hacker News에서 관심 키워드가 들어간 글·댓글을 모은다."""
    from datetime import timedelta

    from narrative_radar.collectors.guard import CollectionBlocked
    from narrative_radar.collectors.hackernews import HackerNewsCollector
    from narrative_radar.collectors.http import PoliteClient
    from narrative_radar.ingest.runner import hackernews_cycle, profile_terms
    from narrative_radar.schemas.enums import RunKind

    ctx = _context("hackernews")
    hasher = _require_allowed(ctx)
    with ctx.sessions() as session:
        # HN은 영어권이라 영문 별칭만 검색어로 쓴다 (검색어마다 요청이 하나씩 늘어난다)
        terms = profile_terms(
            session, ctx.clock.now(), limit=ctx.settings.max_hn_terms, ascii_only=True
        )
    client = PoliteClient(ctx.settings.user_agent, guard=ctx.guard())
    collector = HackerNewsCollector(
        client,
        hasher,
        ctx.clock,
        terms,
        late_threshold=timedelta(minutes=ctx.settings.backfill_after_minutes),
        first_lookback=timedelta(minutes=lookback_minutes),
    )
    typer.echo(f"terms: {terms}")
    try:
        with ctx.run(RunKind.COLLECT, {"source": "hackernews", "terms": terms}) as run_id:
            cycles = 0
            while True:
                r = hackernews_cycle(ctx, collector, run_id)
                cycles += 1
                typer.echo(
                    f"[{ctx.clock.now():%H:%M:%S}] docs={r.documents} new={r.created} "
                    f"revisits={r.revisits} deleted={r.deleted}"
                )
                if not loop or (max_cycles is not None and cycles >= max_cycles):
                    break
                time.sleep(interval)
    except CollectionBlocked as e:
        _stopped(e)
    finally:
        client.close()


@collect_app.command("hackernews-backfill")
def collect_hackernews_backfill(
    days: int = typer.Option(365, min=1, max=3650, help="며칠 전까지 거슬러 올라갈지"),
) -> None:
    """Hacker News의 과거 글·댓글을 받는다. 끊겨도 다시 실행하면 이어 받는다."""
    from datetime import timedelta

    from narrative_radar.collectors.guard import CollectionBlocked
    from narrative_radar.collectors.hackernews import HackerNewsCollector
    from narrative_radar.collectors.http import PoliteClient
    from narrative_radar.ingest.runner import hackernews_backfill, profile_terms
    from narrative_radar.schemas.enums import RunKind

    ctx = _context("hackernews")
    hasher = _require_allowed(ctx)
    with ctx.sessions() as session:
        terms = profile_terms(
            session, ctx.clock.now(), limit=ctx.settings.max_hn_terms, ascii_only=True
        )
    client = PoliteClient(ctx.settings.user_agent, guard=ctx.guard())
    collector = HackerNewsCollector(
        client,
        hasher,
        ctx.clock,
        terms,
        late_threshold=timedelta(minutes=ctx.settings.backfill_after_minutes),
    )
    start = ctx.clock.now() - timedelta(days=days)
    typer.echo(f"terms: {collector.terms} since {start:%Y-%m-%d}")
    try:
        with ctx.run(RunKind.BACKFILL, {"source": "hackernews", "days": days}) as run_id:
            r = hackernews_backfill(
                ctx,
                collector,
                run_id,
                start,
                progress=lambda term, end, new: typer.echo(f"  {term}: ~{end:%Y-%m-%d} new={new}"),
            )
        typer.echo(f"docs={r.documents} new={r.created} requests={r.requests}")
    except CollectionBlocked as e:
        _stopped(e)
    finally:
        client.close()


@collect_app.command("reddit")
def collect_reddit(
    days: int = typer.Option(1, min=1, max=3650, help="처음 실행할 때 거슬러 올라갈 날 수"),
    max_requests: int = typer.Option(
        30, min=1, help="질의 하나에 이번 실행에서 보낼 최대 요청 수. 넘으면 다음에 이어 받는다"
    ),
) -> None:
    """Reddit 투자 서브레딧의 글·댓글을 Arctic Shift 보관본에서 받는다 (D31)."""
    from datetime import timedelta

    from narrative_radar.collectors.guard import CollectionBlocked
    from narrative_radar.collectors.hackernews import minimal_terms
    from narrative_radar.collectors.http import PoliteClient
    from narrative_radar.collectors.rate_limit import MinIntervalLimiter
    from narrative_radar.collectors.reddit import REDDIT_MIN_INTERVAL_SECONDS, RedditArcticCollector
    from narrative_radar.ingest.runner import profile_terms, reddit_cycle
    from narrative_radar.schemas.enums import RunKind

    ctx = _context("reddit_arctic")
    hasher = _require_allowed(ctx)
    with ctx.sessions() as session:
        terms = minimal_terms(
            profile_terms(
                session, ctx.clock.now(), limit=ctx.settings.max_hn_terms, ascii_only=True
            )
        )
    # Arctic Shift는 서버 시간 초과를 422로 알린다. 간격을 두고 두 번까지 다시 묻는다.
    # 3초 간격으로 15분쯤 받자 429로 막혔다(2026-10-17). 무료 공개 서비스라 10초로 늦춘다
    client = PoliteClient(
        ctx.settings.user_agent,
        limiter=MinIntervalLimiter(REDDIT_MIN_INTERVAL_SECONDS),
        guard=ctx.guard(),
        transient_retries=2,
        transient_statuses=(422,),
    )
    collector = RedditArcticCollector(
        client,
        hasher,
        ctx.clock,
        terms,
        late_threshold=timedelta(minutes=ctx.settings.backfill_after_minutes),
    )
    first_start = ctx.clock.now() - timedelta(days=days)
    typer.echo(f"terms: {terms} queries={len(collector.queries())}")
    try:
        with ctx.run(RunKind.COLLECT, {"source": "reddit_arctic", "terms": terms}) as run_id:
            r = reddit_cycle(
                ctx,
                collector,
                run_id,
                first_start,
                max_requests_per_query=max_requests,
                progress=lambda key, at, new: (
                    typer.echo(f"  {key}: ~{at:%Y-%m-%d %H:%M} new={new}") if new else None
                ),
            )
        typer.echo(
            f"docs={r.documents} new={r.created} requests={r.requests} "
            f"unfinished={len(r.unfinished)}"
        )
    except CollectionBlocked as e:
        _stopped(e)
    finally:
        client.close()


@collect_app.command("prices")
def collect_prices_cmd(
    lookback_days: int | None = typer.Option(
        None,
        min=1,
        max=1000,
        help="처음 받는 종목이 거슬러 올라갈 날 수. 기본: NR_PRICE_LOOKBACK_DAYS",
    ),
    extend: bool = typer.Option(
        False, help="이미 받은 종목도 lookback-days까지 과거로 넓힌다 (한 번만 쓴다)"
    ),
) -> None:
    """관심사 트리에 있는 미국·한국 종목의 일봉을 받는다 (토스증권 웹 시세, D27)."""
    from narrative_radar.collectors.guard import CollectionBlocked
    from narrative_radar.collectors.http import PoliteClient
    from narrative_radar.collectors.prices import TossPriceSource
    from narrative_radar.ingest.prices import (
        PriceReport,
        collect_prices,
        resolve_instruments,
        tracked_keys,
    )
    from narrative_radar.schemas.enums import RunKind

    ctx = _context("toss_prices")
    _require_allowed(ctx)
    settings = ctx.settings
    with ctx.sessions() as session:
        keys = tracked_keys(session, ctx, settings.price_max_instruments)
    if not keys:
        typer.echo("관심사 트리에 미국·한국 종목 노드가 없습니다.")
        raise typer.Exit(code=1)
    client = PoliteClient(settings.user_agent, guard=ctx.guard())
    source = TossPriceSource(client, ctx.clock)
    report = PriceReport()
    try:
        with ctx.run(RunKind.COLLECT, {"source": "toss_prices", "keys": keys}) as run_id:
            instruments = resolve_instruments(ctx, source, keys, report)
            collect_prices(
                ctx,
                source,
                run_id,
                instruments,
                lookback_days or settings.price_lookback_days,
                report,
                extend=extend,
            )
    except CollectionBlocked as e:
        _stopped(e)
    finally:
        client.close()
    typer.echo(
        f"instruments={report.instruments} new_bars={report.created} updated={report.updated}"
    )
    if report.unknown:
        typer.echo(f"토스증권에서 찾지 못함: {', '.join(report.unknown)}")


# 스트림이 현재 시각에서 이만큼 안쪽까지 오면 따라잡은 것으로 본다.
CAUGHT_UP_SECONDS = 30


@collect_app.command("bluesky")
def collect_bluesky(
    max_minutes: float | None = typer.Option(None, help="이 시간(분)만큼 받고 끝낸다"),
    until_caught_up: bool = typer.Option(
        False, help="밀린 이벤트를 현재 시각 근처까지 따라잡으면 끝낸다 (주기 실행용)"
    ),
) -> None:
    """Bluesky Jetstream에서 관심 키워드가 들어간 글을 모은다."""
    from datetime import timedelta

    from narrative_radar.collectors.bluesky import JetstreamHandler, JetstreamStream
    from narrative_radar.collectors.gate import get_adapter
    from narrative_radar.collectors.guard import CollectionBlocked
    from narrative_radar.ingest.runner import consume_bluesky, profile_terms
    from narrative_radar.schemas.enums import RunKind

    ctx = _context("bluesky_jetstream")
    hasher = _require_allowed(ctx)
    with ctx.sessions() as session:
        terms = profile_terms(session, ctx.clock.now(), limit=ctx.settings.max_search_terms)
        base_url = get_adapter(session, ctx.source_adapter_id).base_url
    stream = JetstreamStream(ctx.settings.user_agent, ctx.guard(), base_url=f"{base_url}/subscribe")
    handler = JetstreamHandler(
        hasher,
        ctx.clock,
        terms,
        late_threshold=timedelta(minutes=ctx.settings.backfill_after_minutes),
    )
    started = time.monotonic()

    def should_stop() -> bool:
        if max_minutes is not None and time.monotonic() - started >= max_minutes * 60:
            return True
        if until_caught_up and handler.last_time_us is not None:
            behind = ctx.clock.now().timestamp() - handler.last_time_us / 1_000_000
            return behind <= CAUGHT_UP_SECONDS
        return False

    typer.echo(f"terms: {terms}")
    try:
        with ctx.run(RunKind.COLLECT, {"source": "bluesky_jetstream", "terms": terms}) as run_id:
            r = consume_bluesky(ctx, stream, handler, run_id, should_stop=should_stop)
        typer.echo(
            f"events={r.events} matched={r.matched} deleted={r.deleted} "
            f"bytes={stream.bytes_received}"
        )
    except CollectionBlocked as e:
        _stopped(e)


@collect_app.command("bluesky-metrics")
def collect_bluesky_metrics(
    loop: bool = typer.Option(False, help="계속 반복한다"),
    interval: int = typer.Option(120, min=60, help="반복 간격(초). 최소 60"),
) -> None:
    """저장한 Bluesky 글의 좋아요·답글·리포스트 수와 삭제 여부를 다시 확인한다."""
    from narrative_radar.collectors.bluesky import BlueskyMetrics
    from narrative_radar.collectors.guard import CollectionBlocked
    from narrative_radar.collectors.http import PoliteClient
    from narrative_radar.ingest.runner import revisit_bluesky
    from narrative_radar.schemas.enums import RunKind

    # 지표 서버(AppView)는 스트림과 따로 멈추고 따로 다시 켠다 (bluesky_appview)
    ctx = _context("bluesky_appview")
    _require_allowed(ctx)
    client = PoliteClient(ctx.settings.user_agent, guard=ctx.guard())
    metrics = BlueskyMetrics(client, ctx.clock)
    try:
        with ctx.run(RunKind.COLLECT, {"source": "bluesky_appview", "kind": "metrics"}) as run_id:
            while True:
                r = revisit_bluesky(ctx, metrics, run_id)
                typer.echo(
                    f"[{ctx.clock.now():%H:%M:%S}] revisits={r.revisits} deleted={r.deleted}"
                )
                if not loop:
                    break
                time.sleep(interval)
    except CollectionBlocked as e:
        _stopped(e)
    finally:
        client.close()


@collect_app.command("web")
def collect_web_cmd(
    limit: int | None = typer.Option(
        None, min=1, help="가져올 페이지 수. 기본: NR_WEB_MAX_PAGES_PER_RUN"
    ),
) -> None:
    """허용된 사이트의 수집 후보를 우선순위대로 가져와 본문을 채운다 (DECISIONS D25)."""
    import fcntl

    from narrative_radar.collectors.web import SafeWebFetcher, SiteIntervals
    from narrative_radar.ingest.web import collect_web
    from narrative_radar.schemas.enums import RunKind

    ctx = _context("web")
    _require_allowed(ctx)
    settings = ctx.settings
    # 범용 수집기는 한 번에 하나만 돈다 (동시 실행 제한)
    lock_path = settings.db_path.parent / "web-collect.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            typer.echo("다른 범용 수집이 이미 돌고 있습니다.")
            raise typer.Exit(code=1) from None
        fetcher = SafeWebFetcher(
            settings.user_agent,
            SiteIntervals(settings.web_min_interval_seconds),
            max_bytes=settings.web_max_bytes,
            max_redirects=settings.web_max_redirects,
        )
        try:
            with ctx.run(RunKind.COLLECT, {"source": "web"}) as run_id:
                r = collect_web(ctx, fetcher, run_id, limit or settings.web_max_pages_per_run)
        finally:
            fetcher.close()
    typer.echo(
        f"attempted={r.attempted} fetched={r.fetched} upgraded={r.upgraded} created={r.created} "
        f"headline_only={r.headline_only} transient={r.transient} rejected={r.rejected} "
        f"skipped={r.skipped}"
    )
    for site in r.blocked_sites:
        typer.echo(f"사이트 차단: {site} (`nr sites logs {site}`로 원인 확인)")
    if r.stopped:
        typer.echo(f"멈춤: {r.stopped}")

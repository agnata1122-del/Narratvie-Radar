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

    ctx = _context("bluesky_jetstream")
    _require_allowed(ctx)
    client = PoliteClient(ctx.settings.user_agent, guard=ctx.guard())
    metrics = BlueskyMetrics(client, ctx.clock)
    try:
        with ctx.run(RunKind.COLLECT, {"source": "bluesky_jetstream", "kind": "metrics"}) as run_id:
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

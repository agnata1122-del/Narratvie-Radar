"""`nr discover …`: 주제 기반 발견. `nr emergency …`: 전체 긴급 중단 스위치 (DECISIONS D24·D25)."""

import typer

from narrative_radar.cli_collect import _context, _require_allowed, _stopped

discover_app = typer.Typer(help="주제 기반 발견 (docs/DATA_POLICY.md)", no_args_is_help=True)
emergency_app = typer.Typer(help="모든 발견·수집 긴급 중단", no_args_is_help=True)


def _provider(name: str, client):  # type: ignore[no-untyped-def]
    from narrative_radar.discovery.providers import BraveSearchProvider, GdeltProvider

    if name == "gdelt":
        return GdeltProvider(client)
    if name == "brave":
        return BraveSearchProvider()
    typer.echo(f"unknown provider {name!r} (gdelt, brave)")
    raise typer.Exit(code=2)


@discover_app.command("plan")
def discover_plan(
    provider: str = typer.Option("gdelt", help="gdelt | brave(비활성)"),
) -> None:
    """이번에 검색할 노드와 검색식을 보여준다. 네트워크 요청은 하지 않는다."""
    from narrative_radar.discovery.run import plan_queries

    ctx = _context("gdelt")
    with ctx.sessions() as session:
        plan = plan_queries(
            session,
            _provider(provider, None),
            ctx.clock.now(),
            ctx.settings.discovery_max_queries,
        )
    for q in plan.queries:
        typer.echo(f"{q.priority:>3}  {q.profile_name}  d{q.depth}  {q.label}\t{q.query}")
    if plan.unsearchable:
        typer.echo(f"영문 별칭이 없어 건너뜀: {', '.join(plan.unsearchable)}")


@discover_app.command("gdelt")
def discover_gdelt(
    lookback_hours: int | None = typer.Option(
        None,
        help="처음 검색하는 노드가 거슬러 올라갈 시간. 기본: NR_DISCOVERY_FIRST_LOOKBACK_HOURS",
    ),
) -> None:
    """GDELT로 탐색 루트들의 노드를 검색해 수집 후보와 헤드라인 문서를 등록한다."""
    from datetime import timedelta

    from narrative_radar.collectors.guard import CollectionBlocked
    from narrative_radar.collectors.http import PoliteClient
    from narrative_radar.collectors.rate_limit import MinIntervalLimiter
    from narrative_radar.discovery.providers import GdeltProvider
    from narrative_radar.discovery.run import plan_queries, run_discovery
    from narrative_radar.schemas.enums import RunKind

    ctx = _context("gdelt")
    _require_allowed(ctx)
    settings = ctx.settings
    client = PoliteClient(
        settings.user_agent,
        limiter=MinIntervalLimiter(settings.gdelt_min_interval_seconds),
        guard=ctx.guard(),
        transient_retries=settings.gdelt_transient_retries,
    )
    provider = GdeltProvider(client)
    with ctx.sessions() as session:
        plan = plan_queries(session, provider, ctx.clock.now(), settings.discovery_max_queries)
    if not plan.queries:
        typer.echo("검색할 노드가 없습니다. 관심사 그래프를 먼저 만드세요 (`nr db seed`).")
        raise typer.Exit(code=1)
    lookback = timedelta(hours=lookback_hours or settings.discovery_first_lookback_hours)
    try:
        with ctx.run(
            RunKind.COLLECT,
            {"source": "gdelt", "kind": "discovery", "queries": [q.query for q in plan.queries]},
        ) as run_id:
            r = run_discovery(ctx, provider, run_id, plan, lookback, stats=client.stats)
    except CollectionBlocked as e:
        _stopped(e)
        return
    finally:
        client.close()
    typer.echo(
        f"queries={r.queries} items={r.items} registered={r.registered} "
        f"documents={r.documents} duplicates={r.duplicates} capped={r.capped} "
        f"skipped_sites={r.skipped_sites} new_sites={r.new_sites}"
    )
    for line in r.rejected:
        typer.echo(f"검색어 거부: {line}")
    if r.stopped:
        typer.echo(f"멈춤: {r.stopped}")


@discover_app.command("candidates")
def discover_candidates(
    status: str | None = typer.Option(None, help="new | fetched | skipped | blocked | failed"),
    limit: int = typer.Option(30, min=1),
) -> None:
    """수집 후보 목록 (먼저 가져올 것부터)."""
    import sqlalchemy as sa

    from narrative_radar.db.models import DiscoveredUrl
    from narrative_radar.schemas.enums import CandidateStatus

    ctx = _context("gdelt")
    q = sa.select(DiscoveredUrl).order_by(DiscoveredUrl.priority, DiscoveredUrl.discovered_at)
    if status is not None:
        q = q.where(DiscoveredUrl.status == CandidateStatus(status))
    with ctx.sessions() as session:
        for c in session.scalars(q.limit(limit)):
            typer.echo(f"{c.status.value:<8} {c.priority:>6}  {c.domain}\t{c.title[:80]}")


@emergency_app.command("status")
def emergency_status() -> None:
    """긴급 중단 스위치 상태."""
    from narrative_radar.collectors.control import emergency_stop_reason

    with _context("gdelt").sessions() as session:
        reason = emergency_stop_reason(session)
    typer.echo(f"emergency stop: ON ({reason})" if reason else "emergency stop: off")


@emergency_app.command("stop")
def emergency_stop(reason: str = typer.Option(..., help="멈추는 이유")) -> None:
    """모든 발견·수집을 멈춘다. 도는 중인 작업도 다음 요청 전에 멈춘다."""
    from narrative_radar.collectors.control import set_emergency_stop

    ctx = _context("gdelt")
    with ctx.sessions.begin() as session:
        set_emergency_stop(session, ctx.clock, True, reason)
    typer.echo("emergency stop: ON")


@emergency_app.command("resume")
def emergency_resume(reason: str = typer.Option(..., help="원인을 확인한 내용")) -> None:
    """긴급 중단을 푼다. 소스·사이트별 중단 상태는 그대로 남는다."""
    from narrative_radar.collectors.control import set_emergency_stop

    ctx = _context("gdelt")
    with ctx.sessions.begin() as session:
        set_emergency_stop(session, ctx.clock, False, f"resumed: {reason}")
    typer.echo("emergency stop: off")

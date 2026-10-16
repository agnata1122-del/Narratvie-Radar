"""`nr graph …`: 분류 결과를 그래프에 반영하고 관심사 그래프를 확장한다 (M5)."""

import typer

from narrative_radar.core.config import get_settings

graph_app = typer.Typer(help="그래프 갱신", no_args_is_help=True)


@graph_app.command("build")
def graph_build(
    limit: int = typer.Option(1000, min=1, help="한 번에 반영할 글 수"),
    min_relevance: float = typer.Option(
        0.3, min=0, max=1, help="이보다 관련성이 낮으면 반영하지 않음"
    ),
) -> None:
    """분류된 글을 그래프에 반영하고, 관심사별 자동 확장을 실행한다."""
    import sqlalchemy as sa

    from narrative_radar.core.clock import SystemClock
    from narrative_radar.db.models import InterestProfile
    from narrative_radar.db.session import make_engine, make_session_factory
    from narrative_radar.discovery.expansion import expand_profile
    from narrative_radar.graph.builder import GraphBuilder
    from narrative_radar.ingest.runs import finish_run, start_run
    from narrative_radar.schemas.enums import RunKind, RunStatus

    clock = SystemClock()
    factory = make_session_factory(make_engine(get_settings().database_url))
    with factory.begin() as session:
        profiles = session.scalars(sa.select(InterestProfile)).all()
        min_evidence = min((p.minimum_independent_evidence for p in profiles), default=2)
        run = start_run(session, clock, RunKind.BUILD, params={"limit": limit})
        builder = GraphBuilder(
            session,
            clock,
            run.run_id,
            min_relevance=min_relevance,
            min_independent_evidence=min_evidence,
        )
        reports = builder.build(limit)
        expansions = {p.name: expand_profile(session, clock, run.run_id, p) for p in profiles}
        finish_run(run, clock.now(), RunStatus.SUCCEEDED)

    applied = [r for r in reports if r.skipped is None]
    totals = {
        "nodes+": sum(r.nodes_created for r in reports),
        "edges+": sum(r.edges_created for r in reports),
        "confirmed+": sum(r.edges_confirmed for r in reports),
        "claims+": sum(r.claims for r in reports),
        "narratives+": sum(r.narratives_created for r in reports),
    }
    typer.echo(
        f"documents={len(reports)} applied={len(applied)} skipped={len(reports) - len(applied)} "
        + " ".join(f"{k}={v}" for k, v in totals.items())
    )
    for name, e in expansions.items():
        typer.echo(f"profile {name!r}: admitted+={len(e.admitted)} pending+={len(e.pending)}")
    rejected = [msg for r in reports for msg in r.rejected]
    if rejected:
        typer.echo(f"rejected items: {len(rejected)}")
        for msg in rejected[:20]:
            typer.echo(f"  {msg}")

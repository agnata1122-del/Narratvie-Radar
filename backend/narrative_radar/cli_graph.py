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


def _factory():  # type: ignore[no-untyped-def]
    from narrative_radar.db.session import make_engine, make_session_factory

    return make_session_factory(make_engine(get_settings().database_url))


@graph_app.command("duplicates")
def graph_duplicates() -> None:
    """중복일 수 있는 노드 묶음을 보인다 (병합은 `nr graph merge`로 소유자가 정한다)."""
    from narrative_radar.graph.merge import duplicate_candidates

    with _factory()() as session:
        groups = duplicate_candidates(session)
    for g in groups:
        typer.echo(" · ".join(f"{key} ({label})" for key, label in g))
    typer.echo(f"{len(groups)} groups")


@graph_app.command("merge")
def graph_merge(
    old_key: str = typer.Argument(..., help="없앨 쪽 노드 키 (예: TECH:ddr-5)"),
    new_key: str = typer.Argument(..., help="남길 노드 키 (예: TECH:ddr5)"),
    reason: str = typer.Option(..., help="합치는 이유 (이력에 남는다)"),
) -> None:
    """두 노드를 합친다. 옛 노드는 merged가 되고 이름·별칭은 새 노드의 별칭이 된다."""
    from narrative_radar.core.clock import SystemClock
    from narrative_radar.graph.merge import merge_nodes
    from narrative_radar.ingest.runs import finish_run, start_run
    from narrative_radar.schemas.enums import RunKind, RunStatus

    clock = SystemClock()
    with _factory().begin() as session:
        run = start_run(session, clock, RunKind.BUILD, params={"merge": [old_key, new_key]})
        try:
            report = merge_nodes(session, clock, run.run_id, old_key, new_key, reason)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from None
        finish_run(run, clock.now(), RunStatus.SUCCEEDED)
    typer.echo(f"merged {report.old_key} → {report.new_key}; aliases+={report.aliases_added}")


@graph_app.command("tiers")
def graph_tiers(
    limit: int = typer.Option(30, min=1, help="보일 관계 수 (근거 단계·독립 근거 순)"),
) -> None:
    """관계의 근거 단계(사실 확인 / 반복 관측 / 탐색 가설)를 센다. 확정(D6)과 별개다."""
    from collections import Counter

    import sqlalchemy as sa

    from narrative_radar.db.models import Edge, Node
    from narrative_radar.graph.builder import independent_evidence
    from narrative_radar.graph.evidence import TIER_RANK, edge_tiers
    from narrative_radar.schemas.enums import EdgeType

    with _factory()() as session:
        tiers = edge_tiers(session)
        labels = dict(session.execute(sa.select(Node.node_id, Node.label)).all())
        edges = {
            e.edge_id: e
            for e in session.scalars(
                sa.select(Edge).where(Edge.relation_type != EdgeType.CO_MENTIONED_WITH)
            )
        }
        typer.echo(
            " ".join(f"{t.value}={n}" for t, n in Counter(tiers[e] for e in edges).most_common())
        )
        top = sorted(
            edges.values(),
            key=lambda e: (-TIER_RANK[tiers[e.edge_id]], -independent_evidence(session, e.edge_id)),
        )[:limit]
        for e in top:
            typer.echo(
                f"{tiers[e.edge_id].value:10} {labels[e.source_node_id]} "
                f"—{e.relation_type.value}→ {labels[e.target_node_id]} ({e.status.value})"
            )

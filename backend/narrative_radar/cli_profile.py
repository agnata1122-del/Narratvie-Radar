"""`nr profile …`: 소유자가 관심사 트리를 직접 고친다."""

import typer

from narrative_radar.core.config import get_settings

profile_app = typer.Typer(help="관심사 트리", no_args_is_help=True)


@profile_app.command("add")
def profile_add(
    canonical_key: str = typer.Argument(..., help="예: KR:000660, TECH:hbm"),
    label: str = typer.Option(..., help="화면에 보일 이름"),
    node_type: str = typer.Option(..., "--type", help="organization | product | technology | …"),
    alias: list[str] = typer.Option([], help="별칭 (여러 번). 수집 검색어가 된다"),
    depth: int = typer.Option(1, min=1, help="루트에서의 깊이"),
    reason: str = typer.Option(..., help="넣는 이유 (이력에 남는다)"),
    profile_name: str | None = typer.Option(
        None, "--profile", help="관심사 이름 (없으면 최상위 관심사)"
    ),
) -> None:
    """노드를 관심사 트리에 넣는다. 트리의 별칭은 HN·Bluesky 검색어, 상장사는 시세 대상이 된다."""
    import sqlalchemy as sa

    from narrative_radar.core.clock import SystemClock
    from narrative_radar.db.models import InterestProfile
    from narrative_radar.db.session import make_engine, make_session_factory
    from narrative_radar.discovery.curation import admit_node
    from narrative_radar.ingest.runs import finish_run, start_run
    from narrative_radar.schemas.enums import NodeType, RunKind, RunStatus

    clock = SystemClock()
    factory = make_session_factory(make_engine(get_settings().database_url))
    with factory.begin() as session:
        query = sa.select(InterestProfile)
        query = (
            query.where(InterestProfile.name == profile_name)
            if profile_name
            else query.where(InterestProfile.parent_profile_id.is_(None))
        )
        profiles = session.scalars(query).all()
        if len(profiles) != 1:
            typer.echo(
                f"관심사를 하나로 정할 수 없습니다 ({len(profiles)}개). --profile로 고르세요."
            )
            raise typer.Exit(code=2)
        run = start_run(session, clock, RunKind.SETUP, params={"profile_add": canonical_key})
        report = admit_node(
            session,
            clock,
            run.run_id,
            profiles[0],
            canonical_key,
            label,
            NodeType(node_type),
            alias,
            depth,
            reason,
        )
        finish_run(run, clock.now(), RunStatus.SUCCEEDED)
    typer.echo(
        f"{report.canonical_key}: node_created={report.node_created} "
        f"admitted={report.admitted} aliases+={report.aliases_added}"
    )

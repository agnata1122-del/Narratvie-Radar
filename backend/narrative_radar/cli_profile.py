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


def _profile(session, name: str | None):  # type: ignore[no-untyped-def]
    import sqlalchemy as sa

    from narrative_radar.db.models import InterestProfile

    q = sa.select(InterestProfile)
    q = (
        q.where(InterestProfile.name == name)
        if name
        else q.where(InterestProfile.parent_profile_id.is_(None))
    )
    profile = session.scalars(q).first()
    if profile is None:
        raise typer.BadParameter(f"관심사를 찾을 수 없습니다: {name or '(최상위)'}")
    return profile


PROFILE_OPTION = typer.Option(None, "--profile", help="관심사 이름 (없으면 최상위 관심사)")


@profile_app.command("review")
def profile_review(profile_name: str | None = PROFILE_OPTION) -> None:
    """검토 대기 노드와 이유를 보인다. `nr profile approve|exclude`로 정한다."""
    import sqlalchemy as sa

    from narrative_radar.db.models import Node, ProfileNode
    from narrative_radar.db.session import make_engine, make_session_factory
    from narrative_radar.discovery.expansion import latest_decisions
    from narrative_radar.schemas.enums import ProfileNodeStatus

    factory = make_session_factory(make_engine(get_settings().database_url))
    with factory() as session:
        profile = _profile(session, profile_name)
        pending = [
            n
            for n, st in latest_decisions(session, profile.profile_id).items()
            if st == ProfileNodeStatus.PENDING_REVIEW
        ]
        for node_id in pending:
            node = session.get(Node, node_id)
            last = session.scalars(
                sa.select(ProfileNode)
                .where(ProfileNode.profile_id == profile.profile_id, ProfileNode.node_id == node_id)
                .order_by(ProfileNode.available_at.desc(), ProfileNode.decision_id.desc())
            ).first()
            typer.echo(
                f"{node.canonical_key:28} {node.label:30} depth={last.depth} reason={last.reason}"
            )
        typer.echo(f"{len(pending)} pending in {profile.name!r}")


def _decide(key: str, status_name: str, reason: str, profile_name: str | None) -> None:
    import sqlalchemy as sa

    from narrative_radar.core.clock import SystemClock
    from narrative_radar.core.ids import new_id
    from narrative_radar.db.models import Node, ProfileNode
    from narrative_radar.db.session import make_engine, make_session_factory
    from narrative_radar.discovery.expansion import latest_decisions
    from narrative_radar.ingest.runs import finish_run, start_run
    from narrative_radar.schemas.enums import ProfileNodeStatus, RunKind, RunStatus

    status = ProfileNodeStatus(status_name)
    clock = SystemClock()
    factory = make_session_factory(make_engine(get_settings().database_url))
    with factory.begin() as session:
        profile = _profile(session, profile_name)
        node = session.scalar(sa.select(Node).where(Node.canonical_key == key))
        if node is None:
            raise typer.BadParameter(f"노드를 찾을 수 없습니다: {key}")
        if latest_decisions(session, profile.profile_id).get(node.node_id) == status:
            typer.echo(f"{key}: already {status.value}")
            return
        last = session.scalars(
            sa.select(ProfileNode.depth)
            .where(
                ProfileNode.profile_id == profile.profile_id, ProfileNode.node_id == node.node_id
            )
            .order_by(ProfileNode.available_at.desc(), ProfileNode.decision_id.desc())
        ).first()
        run = start_run(session, clock, RunKind.BUILD, params={"decide": [key, status.value]})
        now = clock.now()
        session.add(
            ProfileNode(
                decision_id=new_id("pnd", now),
                profile_id=profile.profile_id,
                node_id=node.node_id,
                status=status,
                depth=last,
                reason=f"owner: {reason}",
                available_at=now,
                run_id=run.run_id,
            )
        )
        finish_run(run, now, RunStatus.SUCCEEDED)
    typer.echo(f"{key}: {status.value} in {profile.name!r}")


@profile_app.command("approve")
def profile_approve(
    canonical_key: str = typer.Argument(..., help="검토 대기 노드 키"),
    reason: str = typer.Option(..., help="넣는 이유 (이력에 남는다)"),
    profile_name: str | None = PROFILE_OPTION,
) -> None:
    """검토 대기 노드를 관심사 트리에 넣는다 (수집 검색어·시세 대상이 된다)."""
    _decide(canonical_key, "admitted", reason, profile_name)


@profile_app.command("exclude")
def profile_exclude(
    canonical_key: str = typer.Argument(..., help="뺄 노드 키"),
    reason: str = typer.Option(..., help="빼는 이유 (이력에 남는다)"),
    profile_name: str | None = PROFILE_OPTION,
) -> None:
    """노드를 관심사 트리에서 뺀다. 자동 확장이 다시 넣지 않는다."""
    _decide(canonical_key, "excluded", reason, profile_name)

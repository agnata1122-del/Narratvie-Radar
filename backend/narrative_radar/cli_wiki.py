"""`nr wiki …`: 관심사 그래프 노드의 위키를 사실로 다시 만든다 (M6)."""

import typer

from narrative_radar.core.config import get_settings

wiki_app = typer.Typer(help="리빙 위키", no_args_is_help=True)


@wiki_app.command("refresh")
def wiki_refresh() -> None:
    """바뀐 노드만 새 리비전으로 저장한다. 이전 리비전은 지우지 않는다."""
    import sqlalchemy as sa

    from narrative_radar.core.clock import SystemClock
    from narrative_radar.db.models import InterestProfile
    from narrative_radar.db.session import make_engine, make_session_factory
    from narrative_radar.ingest.runs import finish_run, start_run
    from narrative_radar.schemas.enums import RunKind, RunStatus
    from narrative_radar.wiki.build import GENERATOR, SCHEMA_VERSION, refresh_wiki

    clock = SystemClock()
    factory = make_session_factory(make_engine(get_settings().database_url))
    with factory.begin() as session:
        run = start_run(
            session, clock, RunKind.WIKI, model=GENERATOR, schema_version=SCHEMA_VERSION
        )
        profiles = list(session.scalars(sa.select(InterestProfile)))
        # 위키는 노드 중심이라 관심사가 여럿이어도 노드마다 한 번만 만든다 (D23)
        created, unchanged = refresh_wiki(session, clock, run.run_id, profiles)
        typer.echo(f"profiles={len(profiles)} revisions+={created} unchanged={unchanged}")
        finish_run(run, clock.now(), RunStatus.SUCCEEDED)

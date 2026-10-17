from pathlib import Path

import typer

from narrative_radar import __version__
from narrative_radar.cli_classify import classify_app
from narrative_radar.cli_collect import collect_app
from narrative_radar.cli_discover import discover_app, emergency_app
from narrative_radar.cli_graph import graph_app
from narrative_radar.cli_sites import sites_app
from narrative_radar.cli_wiki import wiki_app
from narrative_radar.core.config import get_settings

app = typer.Typer(help="Narrative Radar 명령줄 도구", no_args_is_help=True)
db_app = typer.Typer(help="데이터베이스", no_args_is_help=True)
schemas_app = typer.Typer(help="JSON Schema", no_args_is_help=True)
sources_app = typer.Typer(help="데이터 소스 상태 (docs/DATA_POLICY.md)", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(schemas_app, name="schemas")
app.add_typer(sources_app, name="sources")
app.add_typer(collect_app, name="collect")
app.add_typer(discover_app, name="discover")
app.add_typer(emergency_app, name="emergency")
app.add_typer(sites_app, name="sites")
app.add_typer(classify_app, name="classify")
app.add_typer(graph_app, name="graph")
app.add_typer(wiki_app, name="wiki")


@app.command()
def version() -> None:
    """버전을 출력한다."""
    typer.echo(__version__)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """API 서버를 실행한다."""
    import uvicorn

    uvicorn.run(
        "narrative_radar.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


@db_app.command("upgrade")
def db_upgrade() -> None:
    """마이그레이션을 최신으로 적용한다."""
    from narrative_radar.db.migrate import upgrade_to_head

    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    upgrade_to_head(settings.database_url)
    typer.echo(f"migrated: {settings.db_path}")


@db_app.command("seed")
def db_seed() -> None:
    """기본 소스(수집 꺼짐), 기본 관심사, 루트 노드를 만든다. 여러 번 실행해도 안전하다."""
    from narrative_radar.core.clock import SystemClock
    from narrative_radar.db.seed import seed_defaults
    from narrative_radar.db.session import make_engine, make_session_factory, session_scope

    settings = get_settings()
    factory = make_session_factory(make_engine(settings.database_url))
    with session_scope(factory) as session:
        seed_defaults(session, SystemClock())
    typer.echo("seeded")


@db_app.command("init")
def db_init() -> None:
    """upgrade + seed."""
    db_upgrade()
    db_seed()


@schemas_app.command("export")
def schemas_export(out_dir: Path = Path("schemas")) -> None:
    """Pydantic 스키마를 JSON Schema 파일로 내보낸다."""
    from narrative_radar.schemas.export import write_all

    for path in write_all(out_dir):
        typer.echo(f"wrote {path}")


def _sessions():  # type: ignore[no-untyped-def]
    from narrative_radar.db.session import make_engine, make_session_factory

    return make_session_factory(make_engine(get_settings().database_url))


@sources_app.command("list")
def sources_list() -> None:
    """소스별 상태와 수집 가능 여부."""
    import sqlalchemy as sa

    from narrative_radar.collectors.gate import can_collect
    from narrative_radar.db.models import SourceAdapter

    settings = get_settings()
    with _sessions()() as session:
        for a in session.scalars(
            sa.select(SourceAdapter).order_by(SourceAdapter.source_adapter_id)
        ):
            decision = can_collect(settings, a)
            typer.echo(
                f"{a.source_adapter_id}\t{a.access_status.value}\tlive_enabled={a.live_enabled}"
                f"\tcollect={'yes' if decision.allowed else 'no'} ({decision.reason})"
            )


@sources_app.command("report")
def sources_report(hours: int = typer.Option(24, help="최근 몇 시간을 볼지")) -> None:
    """수집 현황: 글 수(실시간·백필), 삭제, 스냅샷, 수집 지연, 시간대별 글 수, 상태 기록."""
    from narrative_radar.core.clock import SystemClock
    from narrative_radar.ingest.report import render, source_report

    with _sessions()() as session:
        typer.echo(render(source_report(session, SystemClock().now(), hours)))


@sources_app.command("enable")
def sources_enable(
    source_id: str,
    accept_data_policy: bool = typer.Option(
        False,
        "--accept-data-policy",
        help="docs/DATA_POLICY.md의 확인 결과와 규칙을 읽고 위험을 감수한다는 확인",
    ),
) -> None:
    """소스를 live로 바꾼다. 실제 수집은 전체 스위치도 켜져 있어야 한다."""
    from narrative_radar.collectors.gate import set_status
    from narrative_radar.core.clock import SystemClock
    from narrative_radar.db.session import session_scope
    from narrative_radar.schemas.enums import SourceAccessStatus

    if not accept_data_policy:
        typer.echo("docs/DATA_POLICY.md를 읽은 뒤 --accept-data-policy를 붙여 다시 실행하세요.")
        raise typer.Exit(code=2)
    with session_scope(_sessions()) as session:
        set_status(
            session,
            source_id,
            SourceAccessStatus.LIVE,
            "enabled by owner via CLI (--accept-data-policy)",
            SystemClock(),
            live_enabled=True,
        )
    typer.echo(f"{source_id}: live")


@sources_app.command("pause")
def sources_pause(source_id: str, reason: str = "paused by owner") -> None:
    """수집을 멈춘다."""
    from narrative_radar.collectors.gate import set_status
    from narrative_radar.core.clock import SystemClock
    from narrative_radar.db.session import session_scope
    from narrative_radar.schemas.enums import SourceAccessStatus

    with session_scope(_sessions()) as session:
        set_status(
            session, source_id, SourceAccessStatus.PAUSED, reason, SystemClock(), live_enabled=False
        )
    typer.echo(f"{source_id}: paused")


@sources_app.command("reset")
def sources_reset(
    source_id: str, reason: str = typer.Option(..., help="중단 원인을 확인한 내용")
) -> None:
    """자동 중단(blocked/stopped)을 해제해 paused로 돌린다. 다시 수집하려면 enable을 실행한다."""
    from narrative_radar.collectors.gate import AUTO_STOP_STATUSES, get_adapter, set_status
    from narrative_radar.core.clock import SystemClock
    from narrative_radar.db.session import session_scope
    from narrative_radar.schemas.enums import SourceAccessStatus

    with session_scope(_sessions()) as session:
        adapter = get_adapter(session, source_id)
        if adapter.access_status not in AUTO_STOP_STATUSES:
            typer.echo(f"{source_id} was not auto-stopped (status: {adapter.access_status.value})")
            raise typer.Exit(code=1)
        set_status(
            session,
            source_id,
            SourceAccessStatus.PAUSED,
            f"auto-stop reviewed: {reason}",
            SystemClock(),
            live_enabled=False,
        )
    typer.echo(f"{source_id}: paused (auto-stop reviewed)")


if __name__ == "__main__":
    app()

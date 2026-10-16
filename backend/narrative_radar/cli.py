from pathlib import Path

import typer

from narrative_radar import __version__
from narrative_radar.core.config import get_settings

app = typer.Typer(help="Narrative Radar 명령줄 도구", no_args_is_help=True)
db_app = typer.Typer(help="데이터베이스", no_args_is_help=True)
schemas_app = typer.Typer(help="JSON Schema", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(schemas_app, name="schemas")


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


if __name__ == "__main__":
    app()

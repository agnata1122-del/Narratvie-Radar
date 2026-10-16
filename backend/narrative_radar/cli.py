import typer

from narrative_radar import __version__

app = typer.Typer(help="Narrative Radar 명령줄 도구", no_args_is_help=True)


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


if __name__ == "__main__":
    app()

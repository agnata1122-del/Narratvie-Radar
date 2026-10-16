from fastapi import FastAPI
from pydantic import BaseModel

from narrative_radar import __version__
from narrative_radar.core.sources import DEFAULT_SOURCES, SourceAccessStatus


class SourceStatusOut(BaseModel):
    id: str
    display_name: str
    access_status: SourceAccessStatus
    live_enabled: bool


class HealthOut(BaseModel):
    status: str
    version: str
    sources: list[SourceStatusOut]


def create_app() -> FastAPI:
    app = FastAPI(title="Narrative Radar API", version=__version__)

    @app.get("/api/health", response_model=HealthOut)
    def health() -> HealthOut:
        return HealthOut(
            status="ok",
            version=__version__,
            sources=[
                SourceStatusOut(
                    id=s.id,
                    display_name=s.display_name,
                    access_status=SourceAccessStatus.NOT_AUTHORIZED,
                    live_enabled=False,
                )
                for s in DEFAULT_SOURCES
            ],
        )

    return app

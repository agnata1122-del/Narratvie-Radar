from typing import Literal

import sqlalchemy as sa
from fastapi import FastAPI
from pydantic import BaseModel

from narrative_radar import __version__
from narrative_radar.api.routes import build_router
from narrative_radar.core.clock import Clock, SystemClock
from narrative_radar.core.config import Settings, get_settings
from narrative_radar.core.sources import DEFAULT_SOURCES
from narrative_radar.db.models import SourceAdapter
from narrative_radar.db.session import make_engine, make_session_factory
from narrative_radar.schemas.enums import SourceAccessStatus


class SourceStatusOut(BaseModel):
    id: str
    display_name: str
    access_status: SourceAccessStatus
    live_enabled: bool


class HealthOut(BaseModel):
    status: Literal["ok"]
    version: str
    database: Literal["ok", "uninitialized"]
    sources: list[SourceStatusOut]


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    sessions = make_session_factory(engine)
    app = FastAPI(title="Narrative Radar API", version=__version__)
    app.include_router(build_router(sessions, clock or SystemClock()))

    @app.get("/api/health", response_model=HealthOut)
    def health() -> HealthOut:
        try:
            with sessions() as session:
                rows = session.scalars(
                    sa.select(SourceAdapter).order_by(SourceAdapter.source_adapter_id)
                ).all()
        except sa.exc.OperationalError:
            rows = None

        if not rows:
            # DB가 아직 없어도 수집하지 않는다는 사실은 그대로 보여준다.
            sources = [
                SourceStatusOut(
                    id=s.id,
                    display_name=s.display_name,
                    access_status=SourceAccessStatus.NOT_AUTHORIZED,
                    live_enabled=False,
                )
                for s in DEFAULT_SOURCES
            ]
        else:
            sources = [
                SourceStatusOut(
                    id=r.source_adapter_id,
                    display_name=r.display_name,
                    access_status=r.access_status,
                    live_enabled=r.live_enabled and settings.live_collection_enabled,
                )
                for r in rows
            ]
        return HealthOut(
            status="ok",
            version=__version__,
            database="ok" if rows else "uninitialized",
            sources=sources,
        )

    return app

from pathlib import Path

import sqlalchemy as sa
from fastapi.testclient import TestClient

from narrative_radar.api.app import create_app
from narrative_radar.core.config import Settings
from narrative_radar.db.models import SourceAdapter
from narrative_radar.db.seed import seed_defaults
from narrative_radar.schemas.enums import SourceAccessStatus


def _client(db_path: Path, **kw: object) -> TestClient:
    return TestClient(create_app(Settings(db_path=db_path, **kw)))


def test_health_without_database_still_reports_no_collection(tmp_path: Path):
    body = _client(tmp_path / "missing.db").get("/api/health").json()
    assert body["database"] == "uninitialized"
    assert {s["id"] for s in body["sources"]} == {"dcinside_stockus", "naver_world_nvda"}
    assert all(s["access_status"] == "not_authorized" for s in body["sources"])
    assert all(s["live_enabled"] is False for s in body["sources"])


def test_health_reads_source_status_from_database(tmp_path, db_url, session, clock):
    seed_defaults(session, clock)
    session.execute(
        sa.update(SourceAdapter)
        .where(SourceAdapter.source_adapter_id == "dcinside_stockus")
        .values(access_status=SourceAccessStatus.BLOCKED, live_enabled=True)
    )
    session.commit()

    db_path = Path(db_url.removeprefix("sqlite:///"))
    body = _client(db_path).get("/api/health").json()
    assert body["database"] == "ok"
    dc = next(s for s in body["sources"] if s["id"] == "dcinside_stockus")
    assert dc["access_status"] == "blocked"
    # 소스별 스위치가 켜져 있어도 전체 스위치가 꺼져 있으면 수집하지 않는다.
    assert dc["live_enabled"] is False

    body = _client(db_path, live_collection_enabled=True).get("/api/health").json()
    dc = next(s for s in body["sources"] if s["id"] == "dcinside_stockus")
    assert dc["live_enabled"] is True

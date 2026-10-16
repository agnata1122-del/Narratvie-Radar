from fastapi.testclient import TestClient

from narrative_radar.api.app import create_app


def test_health_reports_sources_as_not_collecting_by_default():
    client = TestClient(create_app())
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    ids = {s["id"] for s in body["sources"]}
    assert ids == {"dcinside_stockus", "naver_world_nvda"}
    assert all(s["access_status"] == "not_authorized" for s in body["sources"])
    assert all(s["live_enabled"] is False for s in body["sources"])

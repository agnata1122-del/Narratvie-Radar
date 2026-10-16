from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from graphkit import HBM, NV, SKH

from narrative_radar.api.app import create_app
from narrative_radar.core.config import Settings
from narrative_radar.ingest.runs import start_run
from narrative_radar.schemas.enums import RunKind
from narrative_radar.wiki.build import refresh_wiki


@pytest.fixture
def api(g, db_url, clock):
    t0 = clock.now()
    clock.advance(timedelta(hours=1))
    g.confirm(HBM, NV)
    g.build()
    refresh_wiki(g.session, clock, start_run(g.session, clock, RunKind.WIKI).run_id, g.profile)
    t1 = clock.now()
    clock.advance(timedelta(hours=6))
    g.confirm(SKH, HBM, words=("third wording sample", "fourth wording different entirely"))
    g.build()
    g.session.commit()
    client = TestClient(
        create_app(Settings(db_path=Path(db_url.removeprefix("sqlite:///"))), clock)
    )
    return client, t0, t1, clock.now()


def test_overview(api):
    client, *_ = api
    body = client.get("/api/overview").json()
    assert body["profile"]["root_key"] == "US:NVDA"
    assert body["profile"]["max_depth"] == 2
    assert body["counts"]["documents"] == 4
    assert {s["id"] for s in body["sources"]} >= {"hackernews", "bluesky_jetstream"}


def test_state_at_different_times(api):
    client, t0, t1, t2 = api

    def keys(t):
        nodes = client.get("/api/state", params={"as_of": t.isoformat()}).json()["nodes"]
        return {n["canonical_key"] for n in nodes}

    assert keys(t1) == {"US:NVDA", "TECH:hbm"}
    assert keys(t2) == {"US:NVDA", "TECH:hbm", "KR:000660"}
    assert (
        client.get("/api/state", params={"as_of": "2026-10-16T03:00:00"}).status_code == 422
    )  # 시간대 필수


def test_frames_carry_metadata_once_and_values_per_frame(api):
    client, t0, t1, t2 = api
    body = client.get(
        "/api/frames", params={"start": t0.isoformat(), "end": t2.isoformat(), "steps": 5}
    ).json()
    assert len(body["frames"]) == 5
    hbm = next(nid for nid, m in body["nodes"].items() if m["key"] == "TECH:hbm")
    present = [hbm in f["nodes"] for f in body["frames"]]
    assert present[0] is False and present[-1] is True
    assert (
        client.get(
            "/api/frames", params={"start": t2.isoformat(), "end": t0.isoformat()}
        ).status_code
        == 422
    )


def test_changes_and_node_and_edge_details(api):
    client, t0, t1, t2 = api
    body = client.get(
        "/api/changes", params={"since": t1.isoformat(), "until": t2.isoformat()}
    ).json()
    assert ("new_node", "SK hynix") in {(i["kind"], i["label"]) for i in body["items"]}
    rel = next(i for i in body["items"] if i["kind"] == "new_relation")

    edge = client.get(f"/api/edges/{rel['edge_id']}", params={"as_of": t2.isoformat()}).json()
    assert len(edge["evidence"]) == 2 and all(e["url"] for e in edge["evidence"])
    # 그 관계가 생기기 전 시점에는 없다
    assert (
        client.get(f"/api/edges/{rel['edge_id']}", params={"as_of": t1.isoformat()}).status_code
        == 404
    )

    state = client.get("/api/state", params={"as_of": t2.isoformat()}).json()
    hbm = next(n for n in state["nodes"] if n["canonical_key"] == "TECH:hbm")
    detail = client.get(f"/api/nodes/{hbm['node_id']}", params={"as_of": t2.isoformat()}).json()
    assert detail["wiki"]["version"] == 1  # t1에 만든 리비전이 t2에도 최신
    assert detail["node"]["membership"] == "admitted"


def test_viewer_visit_overlay_and_saved_views(api):
    client, t0, t1, t2 = api
    assert (
        client.post("/api/overlays", json={"target_id": "x", "decision": "hidden"}).status_code
        == 401
    )
    first = client.post("/api/viewer/visit").json()
    assert first["previous_seen_at"] is None
    second = client.post("/api/viewer/visit").json()
    assert second["viewer_id"] == first["viewer_id"] and second["previous_seen_at"] is not None

    state = client.get("/api/state").json()
    hbm = next(n for n in state["nodes"] if n["canonical_key"] == "TECH:hbm")
    assert (
        client.post(
            "/api/overlays", json={"target_id": hbm["node_id"], "decision": "rejected"}
        ).status_code
        == 200
    )
    keys = {n["canonical_key"] for n in client.get("/api/state").json()["nodes"]}
    assert "TECH:hbm" not in keys
    client.delete(f"/api/overlays/{hbm['node_id']}")
    assert "TECH:hbm" in {n["canonical_key"] for n in client.get("/api/state").json()["nodes"]}

    view = {
        "view_name": "NVIDIA Emerging Issues",
        "interest": "NVIDIA",
        "filters": {"time_range": "7d"},
    }
    assert client.post("/api/views", json=view).status_code == 200
    assert [v["name"] for v in client.get("/api/views").json()] == ["NVIDIA Emerging Issues"]
    assert (
        client.post(
            "/api/feedback", json={"target_type": "node", "target_id": hbm["node_id"], "rating": 1}
        ).status_code
        == 200
    )

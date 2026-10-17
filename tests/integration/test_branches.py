"""가지: 노드에서 파고들어 그 노드를 루트로 하는 관심사를 만든다 (DECISIONS D23)."""

from datetime import timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from graphkit import HBM, NV, SKH

from narrative_radar.api.app import create_app
from narrative_radar.core.config import Settings
from narrative_radar.db.models import InterestProfile, WikiRevision
from narrative_radar.discovery.branch import BranchError, create_branch, lineage
from narrative_radar.ingest.runner import profile_terms
from narrative_radar.ingest.runs import start_run
from narrative_radar.schemas.enums import ProfileOrigin, RunKind
from narrative_radar.temporal.state import graph_state
from narrative_radar.wiki.build import refresh_wiki


def _keys(state):
    return {n.canonical_key for n in state.nodes}


def _tree(g):
    g.confirm(HBM, NV)  # NVIDIA - HBM
    g.confirm(SKH, HBM, words=("third wording sample", "fourth wording different entirely"))
    g.build()


def test_branch_grows_its_own_tree_from_what_the_shared_graph_already_knows(g, clock):
    _tree(g)
    hbm = g.node("TECH:hbm")
    clock.advance(timedelta(hours=1))
    result = create_branch(g.session, clock, g.profile, hbm.node_id)
    assert result.created
    branch = result.profile
    assert (branch.origin, branch.domain, branch.name) == (ProfileOrigin.BRANCH, "finance", "HBM")
    assert [p.name for p in lineage(g.session, branch)] == ["NVIDIA Research", "HBM"]

    state = graph_state(g.session, branch, clock.now())
    depth = {n.canonical_key: n.depth for n in state.nodes}
    # HBM이 중심: 엔비디아와 SK하이닉스가 모두 1단계
    assert depth == {"TECH:hbm": 0, "US:NVDA": 1, "KR:000660": 1}
    assert not state.reconstructed

    # 같은 노드로 다시 파고들면 새로 만들지 않는다
    again = create_branch(g.session, clock, g.profile, hbm.node_id)
    assert not again.created and again.profile.profile_id == branch.profile_id


def test_before_the_branch_existed_the_tree_is_a_labelled_reconstruction(g, clock):
    g.confirm(HBM, NV)
    g.build()
    t_early = clock.now()
    clock.advance(timedelta(hours=2))
    g.confirm(SKH, HBM, words=("third wording sample", "fourth wording different entirely"))
    g.build()
    clock.advance(timedelta(hours=1))
    branch = create_branch(g.session, clock, g.profile, g.node("TECH:hbm").node_id).profile

    early = graph_state(g.session, branch, t_early)
    assert early.reconstructed
    # 그때 공통 그래프가 알던 것만: SK하이닉스 관계는 아직 없었다
    assert _keys(early) == {"TECH:hbm", "US:NVDA"}
    assert not graph_state(g.session, branch, clock.now()).reconstructed


def test_branch_limits_keep_collection_from_exploding(g, clock):
    _tree(g)
    with pytest.raises(BranchError, match="at most 1 interests"):
        create_branch(g.session, clock, g.profile, g.node("TECH:hbm").node_id, max_profiles=1)
    hbm = create_branch(g.session, clock, g.profile, g.node("TECH:hbm").node_id).profile
    with pytest.raises(BranchError, match="2 levels deep"):
        create_branch(g.session, clock, hbm, g.node("KR:000660").node_id, max_depth=2)


def test_search_terms_grow_with_the_tree_but_stay_capped(g, clock):
    _tree(g)
    terms = profile_terms(g.session, clock.now())
    # 관심사 루트의 표기가 먼저 온다
    assert terms[0] in {"NVIDIA", "NVDA", "엔비디아", "NVIDIA Corporation"}
    assert {"HBM", "SK hynix"} <= set(terms)
    assert len(profile_terms(g.session, clock.now(), limit=3)) == 3
    assert all(t.isascii() for t in profile_terms(g.session, clock.now(), ascii_only=True))


def test_wiki_is_node_centric_so_branches_do_not_flip_revisions(g, clock):
    _tree(g)
    branch = create_branch(g.session, clock, g.profile, g.node("TECH:hbm").node_id).profile
    profiles = [g.profile, branch]
    run = start_run(g.session, clock, RunKind.WIKI).run_id
    created, _ = refresh_wiki(g.session, clock, run, profiles)
    assert created == 3  # NVIDIA, HBM, SK하이닉스 각각 한 번
    clock.advance(timedelta(minutes=5))
    created_again, unchanged = refresh_wiki(g.session, clock, run, profiles)
    assert (created_again, unchanged) == (0, 3)
    versions = g.session.scalars(sa.select(WikiRevision.version)).all()
    assert max(versions) == 1


def test_api_lists_profiles_and_creates_branches_for_visitors(g, clock, db_url):
    _tree(g)
    g.session.commit()
    client = TestClient(
        create_app(Settings(db_path=Path(db_url.removeprefix("sqlite:///"))), clock)
    )
    root = client.get("/api/overview").json()["profile"]
    hbm_id = g.node("TECH:hbm").node_id
    body = {"parent_profile_id": root["profile_id"], "node_id": hbm_id}
    assert client.post("/api/profiles/branch", json=body).status_code == 401  # 방문 먼저
    client.post("/api/viewer/visit")
    made = client.post("/api/profiles/branch", json=body).json()
    assert made["created"] and made["root_label"] == "HBM"

    overview = client.get("/api/overview", params={"profile": made["profile_id"]}).json()
    assert [x["name"] for x in overview["lineage"]] == ["NVIDIA Research", "HBM"]
    parent = client.get("/api/overview").json()
    assert [c["name"] for c in parent["children"]] == ["HBM"]
    assert {p["name"] for p in client.get("/api/profiles").json()} == {"NVIDIA Research", "HBM"}

    detail = client.get(f"/api/nodes/{hbm_id}").json()
    assert detail["branch_profile_id"] == made["profile_id"]

    frames = client.get(
        "/api/frames",
        params={
            "profile": made["profile_id"],
            "start": (clock.now() - timedelta(hours=2)).isoformat(),
            "end": clock.now().isoformat(),
            "steps": 3,
        },
    ).json()
    assert [f["reconstructed"] for f in frames["frames"]] == [True, True, False]
    hbm_values = frames["frames"][-1]["nodes"][hbm_id]
    assert hbm_values[4] == 0  # 깊이
    assert client.get("/api/overview", params={"profile": "prf_nope"}).status_code == 404
    assert g.session.scalar(sa.select(sa.func.count()).select_from(InterestProfile)) == 2

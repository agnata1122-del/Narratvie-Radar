"""가지 정확도 최소 개선 (DECISIONS D39): 근거 단계, 확장 경로 제한, 병합, 검토 대기 결정.

글과 분류 결과는 규칙 확인용으로 직접 만든 최소 예시다 (DECISIONS D0 예외).
"""

import pytest
import sqlalchemy as sa
from graphkit import FILLER, HBM, NV, SKH, affects

from narrative_radar.db.models import GraphEvent, NodeAlias, NodeMention
from narrative_radar.graph.evidence import edge_tiers
from narrative_radar.graph.merge import duplicate_candidates, merge_nodes
from narrative_radar.schemas.enums import (
    EdgeStatus,
    EventType,
    EvidenceTier,
    NodeStatus,
    ProfileNodeStatus,
)

WORDS = ("alpha words", "beta other words entirely")
PLACE = ("Taiwan", "place", "PLACE:taiwan")
DDR5 = ("DDR5", "technology", "TECH:ddr5")
DDR5B = ("DDR-5", "technology", "TECH:ddr-5")


def _twice(g, a, b, rel="AFFECTS", statuses=("community_opinion", "community_opinion")):
    for author, w, ev in zip(("a", "b"), WORDS, statuses, strict=True):
        g.post(
            f"{w} {a[0]} {b[0]} {FILLER}",
            [a, b],
            [(a[0], rel, b[0], {"evidence_status": ev})],
            author=author,
        )


def test_tiers_separate_sourced_repeated_and_hypothesis(g):
    _twice(g, NV, HBM, statuses=("reported_fact", "reported_fact"))
    _twice(g, HBM, SKH)
    _twice(g, NV, SKH, statuses=("speculation", "speculation"))
    g.build()
    ids = {
        name: g.edge(*keys).edge_id
        for name, keys in {
            "sourced": ("US:NVDA", "TECH:hbm"),
            "repeated": ("TECH:hbm", "KR:000660"),
            "hypothesis": ("US:NVDA", "KR:000660"),
        }.items()
    }
    assert all(g.edge(*k).status == EdgeStatus.CONFIRMED for k in [("US:NVDA", "TECH:hbm")])
    tiers = edge_tiers(g.session, ids.values())
    assert {n: tiers[e].value for n, e in ids.items()} == {
        "sourced": "sourced",
        "repeated": "repeated",
        "hypothesis": "hypothesis",
    }


def test_candidate_edge_is_hypothesis(g):
    g.post(f"one take {FILLER}", [NV, HBM], [affects("NVIDIA", "HBM")])
    g.build()
    edge = g.edge("US:NVDA", "TECH:hbm")
    assert edge_tiers(g.session, [edge.edge_id])[edge.edge_id] == EvidenceTier.HYPOTHESIS


def test_speculation_only_and_vague_edges_do_not_expand(g):
    _twice(g, NV, HBM, statuses=("speculation", "speculation"))
    _twice(g, NV, SKH, rel="RELATED_TO")
    g.build()
    assert g.edge("US:NVDA", "TECH:hbm").status == EdgeStatus.CONFIRMED
    assert g.decision("TECH:hbm") != ProfileNodeStatus.ADMITTED
    assert g.decision("KR:000660") != ProfileNodeStatus.ADMITTED


def test_place_nodes_wait_for_review(g):
    _twice(g, NV, PLACE)
    g.build()
    assert g.decision("PLACE:taiwan") == ProfileNodeStatus.PENDING_REVIEW


def test_merge_moves_aliases_and_expansion_follows(g, session, clock):
    _twice(g, NV, DDR5B)
    g.build()
    assert g.decision("TECH:ddr-5") == ProfileNodeStatus.ADMITTED
    g.post(f"gamma lone mention {FILLER}", [DDR5], [])
    g.build()
    groups = duplicate_candidates(session)
    assert any({"TECH:ddr5", "TECH:ddr-5"} <= {k for k, _ in grp} for grp in groups)

    report = merge_nodes(session, clock, g.cls_run, "TECH:ddr-5", "TECH:ddr5", "same thing")
    assert "DDR-5" in report.aliases_added
    old, new = g.node("TECH:ddr-5"), g.node("TECH:ddr5")
    assert old.status == NodeStatus.MERGED and old.merged_into_node_id == new.node_id
    aliases = set(
        session.scalars(sa.select(NodeAlias.alias).where(NodeAlias.node_id == new.node_id))
    )
    assert "DDR-5" in aliases
    assert (
        session.scalars(sa.select(GraphEvent).where(GraphEvent.event_type == EventType.NODE_MERGED))
        .one()
        .payload["merged_into_key"]
        == "TECH:ddr5"
    )
    # 옛 노드의 확정 관계가 새 노드로 읽혀 새 노드가 트리에 들어온다
    g.build()
    assert g.decision("TECH:ddr5") == ProfileNodeStatus.ADMITTED
    # 이후 옛 이름으로 들어온 글은 새 노드로 해석된다
    later = g.post(f"delta later post {FILLER}", [("DDR-5", "technology", None)], [])
    g.build()
    mentioned = set(
        session.scalars(
            sa.select(NodeMention.node_id).where(NodeMention.document_id == later.document_id)
        )
    )
    assert mentioned == {new.node_id}


def test_merge_refuses_bad_requests(g, session, clock):
    _twice(g, NV, HBM)
    g.build()
    with pytest.raises(ValueError):
        merge_nodes(session, clock, g.cls_run, "TECH:hbm", "TECH:hbm", "x")
    with pytest.raises(ValueError):
        merge_nodes(session, clock, g.cls_run, "TECH:nope", "TECH:hbm", "x")
    merge_nodes(session, clock, g.cls_run, "TECH:hbm", "US:NVDA", "test")
    with pytest.raises(ValueError):
        merge_nodes(session, clock, g.cls_run, "US:NVDA", "TECH:hbm", "cycle")


def test_order_prefers_stronger_evidence_within_budget(g, session):
    profile = g.profile
    profile.max_new_nodes_per_day = 1
    _twice(g, NV, SKH)  # 반복 관측
    _twice(g, NV, HBM, statuses=("official_source", "community_opinion"))  # 사실 확인
    g.build()
    assert g.decision("TECH:hbm") == ProfileNodeStatus.ADMITTED
    assert g.decision("KR:000660") == ProfileNodeStatus.PENDING_REVIEW

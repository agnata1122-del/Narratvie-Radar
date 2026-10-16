"""그래프 빌더 규칙 테스트.

글과 분류 결과는 규칙 확인용으로 직접 만든 최소 예시다 (DECISIONS D0 예외).
"""

from datetime import timedelta

import sqlalchemy as sa
from graphkit import FILLER, HBM, NV, NV_KO, POWER, SKH, affects

from narrative_radar.classifiers.session import run_baseline
from narrative_radar.db.models import (
    Document,
    GraphEvent,
    InterestProfile,
    Narrative,
    NarrativeClaim,
    Node,
)
from narrative_radar.discovery.expansion import shortest_depths
from narrative_radar.graph.builder import independent_evidence
from narrative_radar.ingest.runs import start_run
from narrative_radar.schemas.enums import (
    EdgeStatus,
    EdgeType,
    EventCause,
    EventType,
    NodeStatus,
    ProfileNodeStatus,
    RunKind,
)


def test_aliases_resolve_to_the_same_node(g, session):
    d1 = g.doc(f"엔비디아 {FILLER}")
    g.classify(d1, [NV_KO])
    d2 = g.doc(f"NVDA {FILLER} two")
    g.classify(d2, [("NVDA", "company", None)])
    g.build()
    assert session.scalar(sa.select(sa.func.count()).select_from(Node)) == 1


def test_new_entities_are_candidates_with_cause(g, session):
    g.classify(g.doc(f"HBM {FILLER}"), [NV, HBM])
    g.classify(g.doc(f"SK hynix old {FILLER}", mode="backfill"), [SKH])
    g.build()
    assert g.node("TECH:hbm").status == NodeStatus.CANDIDATE
    causes = {
        session.get(Node, e.node_id).canonical_key: e.cause
        for e in session.scalars(
            sa.select(GraphEvent).where(GraphEvent.event_type == EventType.NODE_CREATED)
        )
    }
    assert causes["TECH:hbm"] == EventCause.OBSERVED_NEW
    assert causes["KR:000660"] == EventCause.BACKFILL


def test_copies_by_different_authors_do_not_confirm(g, session):
    text = f"HBM shortage will hit NVIDIA shipments {FILLER}"
    for author in ("a", "b", "c"):
        g.classify(g.doc(text, author=author), [NV, HBM], [affects("HBM", "NVIDIA")])
    g.build()
    edge = g.edge("TECH:hbm", "US:NVDA")
    assert edge.status == EdgeStatus.CANDIDATE
    assert independent_evidence(session, edge.edge_id) == 1
    groups = set(session.scalars(sa.select(Document.derivation_group_id)))
    assert len(groups) == 1


def test_same_author_repeating_does_not_confirm(g, session):
    for i in range(3):
        g.classify(
            g.doc(f"variation {i} {i} {i} HBM hits NVIDIA {FILLER} {i * 7}", author="a"),
            [NV, HBM],
            [affects("HBM", "NVIDIA")],
        )
    g.build()
    assert g.edge("TECH:hbm", "US:NVDA").status == EdgeStatus.CANDIDATE


def test_independent_evidence_confirms_and_activates_nodes(g, session):
    g.classify(
        g.doc(f"first take on HBM and NVIDIA {FILLER}", "a"), [NV, HBM], [affects("HBM", "NVIDIA")]
    )
    g.build()
    assert g.edge("TECH:hbm", "US:NVDA").status == EdgeStatus.CANDIDATE
    g.classify(
        g.doc(f"completely different words about memory supply {FILLER} again", "b"),
        [NV, HBM],
        [affects("HBM", "NVIDIA")],
    )
    g.build()
    assert g.edge("TECH:hbm", "US:NVDA").status == EdgeStatus.CONFIRMED
    assert g.node("TECH:hbm").status == NodeStatus.ACTIVE
    types = [e.event_type for e in session.scalars(sa.select(GraphEvent))]
    assert EventType.EDGE_CONFIRMED in types and EventType.NODE_ACTIVATED in types


def test_co_mentions_are_recorded_but_not_used_for_depth(g, session):
    for author, words in (("a", "one"), ("b", "two other words")):
        g.classify(g.doc(f"{words} NVIDIA and power {FILLER}", author), [NV, POWER])
    g.build()
    co = g.edge("US:NVDA", "TOPIC:data-center-power", EdgeType.CO_MENTIONED_WITH)
    assert co.status == EdgeStatus.CONFIRMED
    # 공동 언급만으로는 관심사 그래프에 들어가지 않는다
    assert g.decision("TOPIC:data-center-power") is None


def test_narratives_are_created_reused_and_linked(g, session):
    first = affects(
        "HBM", "NVIDIA", narrative_proposition="HBM supply limits NVIDIA", narrative_role="supports"
    )
    g.classify(g.doc(f"a {FILLER}", "a"), [NV, HBM], [first])
    similar = affects(
        "HBM",
        "NVIDIA",
        narrative_proposition="HBM supply limits NVIDIA.",
        narrative_role="supports",
    )
    g.classify(g.doc(f"b different words here {FILLER}", "b"), [NV, HBM], [similar])
    g.build()
    narratives = session.scalars(sa.select(Narrative)).all()
    assert len(narratives) == 1
    key = session.get(Node, narratives[0].node_id).canonical_key
    assert key.startswith("NARRATIVE:n-")

    against = affects("HBM", "NVIDIA", narrative_key=key, narrative_role="contradicts")
    g.classify(g.doc(f"c yet another unrelated wording {FILLER}", "c"), [NV, HBM], [against])
    g.build()
    roles = sorted(r.value for r in session.scalars(sa.select(NarrativeClaim.role)))
    assert roles == ["contradicts", "supports", "supports"]
    # 내러티브 노드는 관련 개체와 연결되고, 독립 근거가 쌓이면 확정된다
    link = g.edge(key, "US:NVDA", EdgeType.RELATED_TO)
    assert link.status == EdgeStatus.CONFIRMED


def test_expansion_respects_depth(g, session):
    g.confirm(HBM, NV)  # depth 1
    g.confirm(SKH, HBM)  # depth 2
    far = ("Far Co", "company", "COMPANY:far-co")
    g.confirm(far, SKH)  # depth 3
    g.build()
    assert g.decision("TECH:hbm") == ProfileNodeStatus.ADMITTED
    assert g.decision("KR:000660") == ProfileNodeStatus.ADMITTED
    assert g.decision("COMPANY:far-co") is None


def test_candidate_only_path_goes_to_review(g, session):
    g.classify(g.doc(f"single {FILLER}", "a"), [NV, HBM], [affects("HBM", "NVIDIA")])
    g.build()
    assert g.decision("TECH:hbm") == ProfileNodeStatus.PENDING_REVIEW


def test_daily_budget_and_auto_expand_switch(g, session, clock):
    profile = session.scalars(sa.select(InterestProfile)).one()
    profile.max_new_nodes_per_day = 1
    g.confirm(HBM, NV)
    g.confirm(POWER, NV)
    g.build()
    statuses = {g.decision("TECH:hbm"), g.decision("TOPIC:data-center-power")}
    assert statuses == {ProfileNodeStatus.ADMITTED, ProfileNodeStatus.PENDING_REVIEW}

    clock.advance(timedelta(days=1))  # 다음 날 예산으로 들어온다
    g.build()
    assert g.decision("TOPIC:data-center-power") == ProfileNodeStatus.ADMITTED

    profile.auto_expand = False
    g.confirm(SKH, NV)
    g.build()
    assert g.decision("KR:000660") == ProfileNodeStatus.PENDING_REVIEW


def test_noise_and_review_are_not_applied(g, session):
    noise = g.doc(f"lol {FILLER}")
    g.classify(noise, [NV], is_noise=True)
    review = g.doc(f"maybe sarcasm {FILLER}")
    g.classify(review, [NV, HBM], needs_review=True, review_reason="sarcasm")
    reports = g.build()
    assert [r.skipped for r in reports] == ["noise"]
    assert session.get(Document, noise.document_id).processed_at is not None
    assert session.get(Document, review.document_id).processed_at is None
    assert g.node("TECH:hbm") is None


def test_session_classification_is_preferred_over_baseline(g, session, clock):
    d = g.doc(f"NVIDIA and HBM {FILLER}")
    run_baseline(session, clock, start_run(session, clock, RunKind.CLASSIFY).run_id, "US:NVDA", 10)
    g.classify(d, [NV, HBM])
    g.build()
    assert g.node("TECH:hbm") is not None  # 기준선은 새 개체를 만들지 않는다


def test_available_at_is_processing_time(g, session, clock):
    d = g.doc(f"x {FILLER}")
    g.classify(d, [NV, HBM])
    clock.advance(timedelta(hours=2))
    g.build()
    node = g.node("TECH:hbm")
    assert node.available_at == clock.now()
    assert session.get(Document, d.document_id).available_at == clock.now()


def test_shortest_depths():
    edges = [("r", "a"), ("a", "b"), ("b", "c")]
    assert shortest_depths(edges, "r", 2) == {"r": 0, "a": 1, "b": 2}

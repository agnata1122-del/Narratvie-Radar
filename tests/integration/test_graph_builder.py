"""그래프 빌더 규칙 테스트.

글과 분류 결과는 규칙 확인용으로 직접 만든 최소 예시다 (DECISIONS D0 예외).
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from narrative_radar.classifiers.session import ingest_records, run_baseline
from narrative_radar.db.models import (
    Document,
    Edge,
    GraphEvent,
    InterestProfile,
    Narrative,
    NarrativeClaim,
    Node,
    ProfileNode,
)
from narrative_radar.db.seed import seed_defaults
from narrative_radar.discovery.expansion import expand_profile, shortest_depths
from narrative_radar.graph.builder import GraphBuilder, independent_evidence
from narrative_radar.ingest.runs import start_run
from narrative_radar.ingest.store import DocumentStore
from narrative_radar.schemas.document import DocumentIn
from narrative_radar.schemas.enums import (
    EdgeStatus,
    EdgeType,
    EventCause,
    EventType,
    NodeStatus,
    ProfileNodeStatus,
    RunKind,
)

T0 = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
FILLER = "this example sentence has enough words for the copy detector to work"


@pytest.fixture
def g(session, clock):
    seed_defaults(session, clock)
    collect = start_run(session, clock, RunKind.COLLECT)
    store = DocumentStore(session, collect.run_id, "test")
    cls_run = start_run(session, clock, RunKind.CLASSIFY).run_id
    counter = {"n": 0}

    class Helper:
        def doc(self, text, author="a", mode="live"):
            counter["n"] += 1
            ext = str(counter["n"])
            r = store.save(
                DocumentIn(
                    source_adapter_id="hackernews",
                    external_id=ext,
                    source_url=f"https://news.ycombinator.com/item?id={ext}",
                    title="",
                    body_text=text,
                    author_hash=author * 64,
                    published_at=T0,
                    observed_at=T0,
                    content_access_status="permitted",
                    ingest_mode=mode,
                )
            )
            return session.get(Document, r.document_id)

        def classify(self, doc, entities, claims=(), **kw):
            output = {
                "relevance": 0.9,
                "is_noise": False,
                "entities": [{"name": n, "type": t, "canonical_key": k} for n, t, k in entities],
                "stance": "neutral",
                "claims": [
                    {
                        "subject": s,
                        "predicate": p,
                        "object": o,
                        "polarity": "neutral",
                        "stance": "neutral",
                        "evidence_status": "community_opinion",
                        "excerpt": "example",
                        **extra,
                    }
                    for s, p, o, extra in claims
                ],
                "needs_review": False,
            } | kw
            line = json.dumps(
                {"document_id": doc.document_id, "content_hash": doc.content_hash, "output": output}
            )
            report = ingest_records(session, clock, [line], "test-model", cls_run)
            assert not report.errors, report.errors

        def build(self):
            run = start_run(session, clock, RunKind.BUILD).run_id
            reports = GraphBuilder(session, clock, run).build(100)
            profile = session.scalars(sa.select(InterestProfile)).one()
            expand_profile(session, clock, run, profile)
            return reports

        def node(self, key):
            return session.scalar(sa.select(Node).where(Node.canonical_key == key))

        def edge(self, a, b, rel=EdgeType.AFFECTS):
            na, nb = self.node(a), self.node(b)
            return session.scalar(
                sa.select(Edge).where(
                    Edge.relation_type == rel,
                    sa.or_(
                        sa.and_(
                            Edge.source_node_id == na.node_id, Edge.target_node_id == nb.node_id
                        ),
                        sa.and_(
                            Edge.source_node_id == nb.node_id, Edge.target_node_id == na.node_id
                        ),
                    ),
                )
            )

        def decision(self, key):
            node = self.node(key)
            rows = session.scalars(
                sa.select(ProfileNode.status)
                .where(ProfileNode.node_id == node.node_id)
                .order_by(ProfileNode.available_at, ProfileNode.decision_id)
            ).all()
            return rows[-1] if rows else None

    return Helper()


NV = ("NVIDIA", "company", "US:NVDA")
NV_KO = ("엔비디아", "company", None)
HBM = ("HBM", "technology", "TECH:hbm")
SKH = ("SK hynix", "company", "KR:000660")
POWER = ("data center power", "topic", "TOPIC:data-center-power")


def affects(s, o, **extra):
    return (s, "AFFECTS", o, extra)


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


def _confirm(g, a, b):
    for author, words in (("a", "alpha words"), ("b", "beta other words entirely")):
        g.classify(g.doc(f"{words} {a[0]} {b[0]} {FILLER}", author), [a, b], [affects(a[0], b[0])])


def test_expansion_respects_depth(g, session):
    _confirm(g, HBM, NV)  # depth 1
    _confirm(g, SKH, HBM)  # depth 2
    far = ("Far Co", "company", "COMPANY:far-co")
    _confirm(g, far, SKH)  # depth 3
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
    _confirm(g, HBM, NV)
    _confirm(g, POWER, NV)
    g.build()
    statuses = {g.decision("TECH:hbm"), g.decision("TOPIC:data-center-power")}
    assert statuses == {ProfileNodeStatus.ADMITTED, ProfileNodeStatus.PENDING_REVIEW}

    clock.advance(timedelta(days=1))  # 다음 날 예산으로 들어온다
    g.build()
    assert g.decision("TOPIC:data-center-power") == ProfileNodeStatus.ADMITTED

    profile.auto_expand = False
    _confirm(g, SKH, NV)
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

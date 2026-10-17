"""그래프 관련 통합 테스트 도우미.

글과 분류 결과는 규칙 확인용으로 직접 만든 최소 예시다 (DECISIONS D0 예외).
"""

import hashlib
import json
from datetime import UTC, datetime

import sqlalchemy as sa

from narrative_radar.classifiers.session import ingest_records
from narrative_radar.db.models import Document, Edge, InterestProfile, Node, ProfileNode
from narrative_radar.db.seed import seed_defaults
from narrative_radar.discovery.expansion import expand_profile
from narrative_radar.graph.builder import GraphBuilder
from narrative_radar.ingest.runs import start_run
from narrative_radar.ingest.store import DocumentStore
from narrative_radar.schemas.document import DocumentIn
from narrative_radar.schemas.enums import EdgeType, RunKind

T0 = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
FILLER = "this example sentence has enough words for the copy detector to work"

NV = ("NVIDIA", "organization", "US:NVDA")
NV_KO = ("엔비디아", "organization", None)
HBM = ("HBM", "technology", "TECH:hbm")
SKH = ("SK hynix", "organization", "KR:000660")
POWER = ("data center power", "topic", "TOPIC:data-center-power")


def affects(s, o, **extra):
    return (s, "AFFECTS", o, extra)


class GraphKit:
    def __init__(self, session, clock):
        self.session = session
        self.clock = clock
        seed_defaults(session, clock)
        collect = start_run(session, clock, RunKind.COLLECT)
        self.store = DocumentStore(session, collect.run_id, "test")
        self.cls_run = start_run(session, clock, RunKind.CLASSIFY).run_id
        self.n = 0

    @property
    def profile(self) -> InterestProfile:
        return self.session.scalars(sa.select(InterestProfile)).one()

    def doc(self, text, author="a", mode="live", published=None):
        self.n += 1
        ext = str(self.n)
        published = published or self.clock.now()
        r = self.store.save(
            DocumentIn(
                source_adapter_id="hackernews",
                external_id=ext,
                source_url=f"https://news.ycombinator.com/item?id={ext}",
                title="",
                body_text=text,
                author_hash=hashlib.sha256(author.encode()).hexdigest(),
                published_at=published,
                observed_at=max(published, self.clock.now()),
                content_access_status="permitted",
                ingest_mode=mode,
            )
        )
        return self.session.get(Document, r.document_id)

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
                    "excerpt": extra.pop("excerpt", "example"),
                    **extra,
                }
                for s, p, o, extra in [(c[0], c[1], c[2], dict(c[3])) for c in claims]
            ],
            "needs_review": False,
        } | kw
        line = json.dumps(
            {"document_id": doc.document_id, "content_hash": doc.content_hash, "output": output}
        )
        report = ingest_records(self.session, self.clock, [line], "test-model", self.cls_run)
        assert not report.errors, report.errors

    def build(self):
        run = start_run(self.session, self.clock, RunKind.BUILD).run_id
        reports = GraphBuilder(self.session, self.clock, run).build(100)
        expand_profile(self.session, self.clock, run, self.profile)
        return reports

    def post(self, text, entities, claims=(), author="a", mode="live", published=None, **output):
        """글 하나를 올리고 분류한다 (반영은 build). output은 분류 출력 필드를 덮어쓴다."""
        d = self.doc(text, author=author, mode=mode, published=published)
        self.classify(d, entities, claims, **output)
        return d

    def node(self, key):
        return self.session.scalar(sa.select(Node).where(Node.canonical_key == key))

    def edge(self, a, b, rel=EdgeType.AFFECTS):
        na, nb = self.node(a), self.node(b)
        return self.session.scalar(
            sa.select(Edge).where(
                Edge.relation_type == rel,
                sa.or_(
                    sa.and_(Edge.source_node_id == na.node_id, Edge.target_node_id == nb.node_id),
                    sa.and_(Edge.source_node_id == nb.node_id, Edge.target_node_id == na.node_id),
                ),
            )
        )

    def decision(self, key):
        node = self.node(key)
        rows = self.session.scalars(
            sa.select(ProfileNode.status)
            .where(ProfileNode.node_id == node.node_id)
            .order_by(ProfileNode.available_at, ProfileNode.decision_id)
        ).all()
        return rows[-1] if rows else None

    def confirm(self, a, b, words=("alpha words", "beta other words entirely")):
        """서로 다른 작성자·다른 글 두 개로 a→b 관계를 확정 조건까지 쌓는다."""
        for author, w in zip(("a", "b"), words, strict=True):
            self.post(f"{w} {a[0]} {b[0]} {FILLER}", [a, b], [affects(a[0], b[0])], author=author)

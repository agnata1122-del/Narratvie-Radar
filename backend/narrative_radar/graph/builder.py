"""분류 결과를 그래프에 반영한다 (M5).

- 이 단계에서 쓰는 모든 행의 available_at은 처리 시각이다. 과거 상태 복원은 이 값을 기준으로 한다.
- 이벤트의 원인은 글의 수집 방식으로 정한다: backfill로 받은 글이면 backfill, 아니면 observed_new.
- 관계는 독립 근거가 기준 이상이면 관측 확정(confirmed)이 된다 (DECISIONS D6).
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from itertools import combinations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.classifiers import rule_based
from narrative_radar.classifiers.session import EXTRACTION_VERSION, PROMPT_VERSION
from narrative_radar.core.clock import Clock
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import (
    Claim,
    ClassificationRun,
    DerivationGroup,
    Document,
    Edge,
    EdgeEvidence,
    GraphEvent,
    Narrative,
    NarrativeClaim,
    Node,
    NodeAlias,
    NodeMention,
    RawDocument,
)
from narrative_radar.graph import fingerprint
from narrative_radar.graph.changeset import ChangeSet, build_changeset
from narrative_radar.graph.resolve import EntityResolver, Resolution
from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas import extraction
from narrative_radar.schemas.classification import ClaimExtract, ClassificationOutput
from narrative_radar.schemas.enums import (
    AliasOrigin,
    ClassificationStatus,
    EdgeStatus,
    EdgeType,
    EventCause,
    EventType,
    IngestMode,
    NarrativeRole,
    NarrativeState,
    NodeStatus,
    NodeType,
)

# 방향이 없는 관계는 노드 순서를 정렬해 하나로 저장한다.
SYMMETRIC = frozenset({EdgeType.COMPETES_WITH, EdgeType.RELATED_TO, EdgeType.CO_MENTIONED_WITH})
MAX_COMENTION_NODES = 12
DERIVATION_WINDOW = timedelta(days=7)
NARRATIVE_SIMILARITY = 0.85
# 분류기를 고르는 순서: v3 추출(D38) → v2 세션 분류 → 규칙 기반 기준선.
# 세션 분류는 도메인 팩 버전을 붙여 기록하므로(`extraction.v3+finance.v2`) 접두어로 찾는다.
CLASSIFIER_PREFERENCE = (EXTRACTION_VERSION, PROMPT_VERSION, rule_based.MODEL_LABEL)


def _version_filter(version: str) -> sa.ColumnElement[bool]:
    column = ClassificationRun.prompt_version
    if version in (EXTRACTION_VERSION, PROMPT_VERSION):
        return sa.or_(column == version, column.startswith(f"{version}+", autoescape=True))
    return column == version


@dataclass
class ApplyReport:
    document_id: str
    skipped: str | None = None
    nodes_created: int = 0
    edges_created: int = 0
    edges_confirmed: int = 0
    claims: int = 0
    narratives_created: int = 0
    rejected: list[str] = field(default_factory=list)


def independent_evidence(session: Session, edge_id: str, as_of: datetime | None = None) -> int:
    """서로 다른 복사 묶음이면서 서로 다른 작성자인 근거 수 (DECISIONS D6)."""
    q = sa.select(
        EdgeEvidence.derivation_group_id, EdgeEvidence.author_hash, EdgeEvidence.document_id
    ).where(EdgeEvidence.edge_id == edge_id)
    if as_of is not None:
        q = q.where(EdgeEvidence.available_at <= as_of)
    rows = session.execute(q).all()
    groups = {g or f"doc:{d}" for g, _, d in rows}
    authors = {a or f"doc:{d}" for _, a, d in rows}
    return min(len(groups), len(authors))


class GraphBuilder:
    def __init__(
        self,
        session: Session,
        clock: Clock,
        run_id: str,
        min_relevance: float = 0.3,
        min_independent_evidence: int = 2,
    ) -> None:
        self.session = session
        self.clock = clock
        self.run_id = run_id
        self.min_relevance = min_relevance
        self.min_independent_evidence = min_independent_evidence
        self.resolver = EntityResolver(session)
        self._groups: list[tuple[int, str]] | None = None

    # --- 대기열 ---------------------------------------------------------------------------

    def pending(self, limit: int) -> list[tuple[Document, ClassificationRun]]:
        # 수집은 분류보다 훨씬 많다. 반영할 분류가 있는 글만 고른다 (없는 글이 앞을 막지 않게)
        classified = (
            sa.select(ClassificationRun.classification_id)
            .where(
                ClassificationRun.document_id == Document.document_id,
                ClassificationRun.content_hash == Document.content_hash,
                ClassificationRun.status == ClassificationStatus.ACCEPTED,
            )
            .exists()
        )
        docs = self.session.scalars(
            sa.select(Document)
            .where(
                Document.processed_at.is_(None),
                Document.deleted_observed_at.is_(None),
                classified,
            )
            .order_by(Document.published_at)
            .limit(limit * 5)
        ).all()
        out = []
        for doc in docs:
            cls = self._classification_for(doc)
            if cls is not None:
                out.append((doc, cls))
            if len(out) >= limit:
                break
        return out

    def _classification_for(self, doc: Document) -> ClassificationRun | None:
        for version in CLASSIFIER_PREFERENCE:
            cls = self.session.scalars(
                sa.select(ClassificationRun)
                .where(
                    ClassificationRun.document_id == doc.document_id,
                    ClassificationRun.content_hash == doc.content_hash,
                    _version_filter(version),
                    ClassificationRun.status == ClassificationStatus.ACCEPTED,
                )
                .order_by(ClassificationRun.completed_at.desc())
            ).first()
            if cls is not None:
                return cls
        return None

    # --- 반영 -----------------------------------------------------------------------------

    def apply(self, doc: Document, cls: ClassificationRun) -> ApplyReport:
        now = self.clock.now()
        report = ApplyReport(doc.document_id)
        if cls.schema_version == extraction.SCHEMA_VERSION:
            # 근거 검증을 통과한 사건·관계만 v2 형식 관계로 넘긴다 (사건 자체는 기록에 남는다)
            output = extraction.graph_view(extraction.ExtractionOutput.model_validate(cls.output))
        else:
            output = ClassificationOutput.model_validate(cls.output)
        cs: ChangeSet = build_changeset(self.resolver, output, self.min_relevance)
        report.rejected = list(cs.rejected)
        cause = (
            EventCause.BACKFILL
            if doc.ingest_mode == IngestMode.BACKFILL
            else EventCause.OBSERVED_NEW
        )

        self._assign_derivation_group(doc, now)
        if cs.skip_reason is not None:
            report.skipped = cs.skip_reason
            self._mark_processed(doc, now)
            return report

        node_ids: dict[str, str] = {}  # 해석 결과 → 노드 ID
        for r in cs.entities:
            node_id, created = self._node_for(r, doc, now, cause)
            node_ids[_res_key(r)] = node_id
            report.nodes_created += created
        for node_id in set(node_ids.values()):
            self._mention(node_id, doc, now)

        touched: set[str] = set()
        for proposed in cs.claims:
            c = proposed.claim
            src, dst = node_ids[_res_key(proposed.subject)], node_ids[_res_key(proposed.object)]
            claim = Claim(
                claim_id=new_id("clm", now),
                document_id=doc.document_id,
                classification_id=cls.classification_id,
                subject_text=c.subject,
                subject_node_id=src,
                predicate=c.predicate,
                object_text=c.object,
                object_node_id=dst,
                polarity=c.polarity,
                stance=c.stance,
                evidence_status=c.evidence_status,
                excerpt=c.excerpt[:500],
                created_at=now,
                available_at=now,
            )
            self.session.add(claim)
            self.session.flush()
            report.claims += 1
            edge, created = self._edge(src, dst, c.predicate, now, cause, doc)
            report.edges_created += created
            self._evidence(edge, doc, claim.claim_id, now)
            touched.add(edge.edge_id)

            narrative_node = self._narrative_for(c, claim, now, cause, report)
            if narrative_node is not None:
                # 내러티브를 지지·반박한 글은 그 내러티브를 언급한 글로 센다 (관심도·휴면 판정)
                self._mention(narrative_node, doc, now)
                for target in (src, dst):
                    nedge, created = self._edge(
                        narrative_node, target, EdgeType.RELATED_TO, now, cause, doc
                    )
                    report.edges_created += created
                    self._evidence(nedge, doc, claim.claim_id, now)
                    touched.add(nedge.edge_id)

        mentioned = sorted(set(node_ids.values()))[:MAX_COMENTION_NODES]
        for a, b in combinations(mentioned, 2):
            edge, created = self._edge(a, b, EdgeType.CO_MENTIONED_WITH, now, cause, doc)
            report.edges_created += created
            self._evidence(edge, doc, None, now)
            touched.add(edge.edge_id)

        for edge_id in sorted(touched):
            report.edges_confirmed += self._maybe_confirm(edge_id, now, cause, doc)

        self._mark_processed(doc, now)
        return report

    def build(self, limit: int) -> list[ApplyReport]:
        return [self.apply(doc, cls) for doc, cls in self.pending(limit)]

    # --- 내부 -----------------------------------------------------------------------------

    def _mark_processed(self, doc: Document, now: datetime) -> None:
        doc.processed_at = now
        doc.available_at = now
        self.session.flush()

    def _event(
        self,
        event_type: EventType,
        cause: EventCause,
        now: datetime,
        doc: Document,
        **targets: object,
    ) -> None:
        payload = targets.pop("payload", {})
        self.session.add(
            GraphEvent(
                event_id=new_id("evt", now),
                event_type=event_type,
                cause=cause,
                payload=payload,
                evidence_document_ids=[doc.document_id],
                event_time=doc.published_at,
                recorded_at=now,
                available_at=now,
                run_id=self.run_id,
                **targets,
            )
        )

    def _assign_derivation_group(self, doc: Document, now: datetime) -> None:
        if doc.derivation_group_id is not None:
            return
        raw = self.session.get(RawDocument, doc.document_id)
        text = "\n".join(p for p in (doc.title, raw.body_text if raw else "") if p)
        sh = fingerprint.simhash(text)
        group_id = None
        if sh is not None:
            for value, gid in self._recent_groups(now):
                if fingerprint.hamming(value, sh) <= fingerprint.MAX_HAMMING:
                    group_id = gid
                    break
        if group_id is None:
            group_id = new_id("dgp", now)
            self.session.add(
                DerivationGroup(
                    group_id=group_id,
                    fingerprint=fingerprint.to_hex(sh)
                    if sh is not None
                    else f"doc:{doc.document_id}"[:128],
                    created_at=now,
                    available_at=now,
                )
            )
            if sh is not None:
                self._recent_groups(now).append((sh, group_id))
        doc.derivation_group_id = group_id
        self.session.flush()

    def _recent_groups(self, now: datetime) -> list[tuple[int, str]]:
        if self._groups is None:
            rows = self.session.execute(
                sa.select(DerivationGroup.fingerprint, DerivationGroup.group_id).where(
                    DerivationGroup.created_at >= now - DERIVATION_WINDOW,
                    ~DerivationGroup.fingerprint.startswith("doc:"),
                )
            ).all()
            self._groups = [(fingerprint.from_hex(f), g) for f, g in rows]
        return self._groups

    def _node_for(
        self, r: Resolution, doc: Document, now: datetime, cause: EventCause
    ) -> tuple[str, bool]:
        alias = normalize_text(r.mention.name)
        if r.node_id is not None:
            self._add_alias(r.node_id, r.mention.name, alias, now)
            return r.node_id, False
        assert r.new_key is not None
        existing = self.session.scalar(sa.select(Node).where(Node.canonical_key == r.new_key))
        if existing is not None:  # 같은 배치에서 이미 만든 키
            self._add_alias(existing.node_id, r.mention.name, alias, now)
            return existing.node_id, False
        node = Node(
            node_id=new_id("nod", now),
            canonical_key=r.new_key,
            node_type=r.mention.type,
            label=r.mention.name[:300],
            status=NodeStatus.CANDIDATE,
            created_at=now,
            available_at=now,
            created_run_id=self.run_id,
        )
        self.session.add(node)
        self.session.flush()
        self._add_alias(node.node_id, r.mention.name, alias, now)
        self._event(EventType.NODE_CREATED, cause, now, doc, node_id=node.node_id)
        return node.node_id, True

    def _mention(self, node_id: str, doc: Document, now: datetime) -> None:
        exists = self.session.scalar(
            sa.select(NodeMention.mention_id).where(
                NodeMention.node_id == node_id, NodeMention.document_id == doc.document_id
            )
        )
        if exists:
            return
        self.session.add(
            NodeMention(
                mention_id=new_id("mnt", now),
                node_id=node_id,
                document_id=doc.document_id,
                source_adapter_id=doc.source_adapter_id,
                derivation_group_id=doc.derivation_group_id,
                author_hash=doc.author_hash,
                published_at=doc.published_at,
                available_at=now,
                run_id=self.run_id,
            )
        )
        self.session.flush()

    def _add_alias(self, node_id: str, alias: str, normalized: str, now: datetime) -> None:
        exists = self.session.scalar(
            sa.select(NodeAlias.alias_id).where(
                NodeAlias.node_id == node_id, NodeAlias.alias_normalized == normalized
            )
        )
        if exists:
            return
        self.session.add(
            NodeAlias(
                alias_id=new_id("als", now),
                node_id=node_id,
                alias=alias[:300],
                alias_normalized=normalized[:300],
                origin=AliasOrigin.LLM,
                created_at=now,
                available_at=now,
            )
        )
        self.resolver.remember_alias(normalized, node_id)

    def _edge(
        self,
        src: str,
        dst: str,
        relation: EdgeType,
        now: datetime,
        cause: EventCause,
        doc: Document,
    ) -> tuple[Edge, bool]:
        if relation in SYMMETRIC and src > dst:
            src, dst = dst, src
        edge = self.session.scalar(
            sa.select(Edge).where(
                Edge.source_node_id == src,
                Edge.target_node_id == dst,
                Edge.relation_type == relation,
            )
        )
        if edge is not None:
            return edge, False
        edge = Edge(
            edge_id=new_id("edg", now),
            source_node_id=src,
            target_node_id=dst,
            relation_type=relation,
            status=EdgeStatus.CANDIDATE,
            created_at=now,
            available_at=now,
            created_run_id=self.run_id,
        )
        self.session.add(edge)
        self.session.flush()
        self._event(
            EventType.EDGE_CREATED,
            cause,
            now,
            doc,
            edge_id=edge.edge_id,
            payload={"source": src, "target": dst, "relation": relation.value},
        )
        return edge, True

    def _evidence(self, edge: Edge, doc: Document, claim_id: str | None, now: datetime) -> None:
        exists = self.session.scalar(
            sa.select(EdgeEvidence.evidence_id).where(
                EdgeEvidence.edge_id == edge.edge_id, EdgeEvidence.document_id == doc.document_id
            )
        )
        if exists:
            return
        self.session.add(
            EdgeEvidence(
                evidence_id=new_id("evd", now),
                edge_id=edge.edge_id,
                document_id=doc.document_id,
                claim_id=claim_id,
                derivation_group_id=doc.derivation_group_id,
                author_hash=doc.author_hash,
                available_at=now,
                run_id=self.run_id,
            )
        )
        self.session.flush()

    def _maybe_confirm(self, edge_id: str, now: datetime, cause: EventCause, doc: Document) -> int:
        edge = self.session.get_one(Edge, edge_id)
        if edge.status != EdgeStatus.CANDIDATE:
            return 0
        count = independent_evidence(self.session, edge_id)
        if count < self.min_independent_evidence:
            return 0
        edge.status = EdgeStatus.CONFIRMED
        self._event(
            EventType.EDGE_CONFIRMED,
            cause,
            now,
            doc,
            edge_id=edge_id,
            payload={"independent_evidence": count},
        )
        if edge.relation_type != EdgeType.CO_MENTIONED_WITH:
            for node_id in (edge.source_node_id, edge.target_node_id):
                node = self.session.get_one(Node, node_id)
                if node.status == NodeStatus.CANDIDATE:
                    node.status = NodeStatus.ACTIVE
                    self._event(EventType.NODE_ACTIVATED, cause, now, doc, node_id=node_id)
        return 1

    def _narrative_for(
        self, c: ClaimExtract, claim: Claim, now: datetime, cause: EventCause, report: ApplyReport
    ) -> str | None:
        if c.narrative_key is None and c.narrative_proposition is None:
            return None
        role = c.narrative_role or NarrativeRole.SUPPORTS
        narrative: Narrative | None = None
        if c.narrative_key is not None:
            node = self.session.scalar(sa.select(Node).where(Node.canonical_key == c.narrative_key))
            narrative = (
                self.session.scalar(sa.select(Narrative).where(Narrative.node_id == node.node_id))
                if node is not None
                else None
            )
            if narrative is None:
                report.rejected.append(f"unknown narrative_key {c.narrative_key!r}")
                return None
        else:
            proposition = c.narrative_proposition or ""
            narrative = self._similar_narrative(proposition)
            if narrative is None:
                narrative = self._create_narrative(proposition, now, cause, claim)
                report.narratives_created += 1
        self.session.add(
            NarrativeClaim(
                assignment_id=new_id("nca", now),
                narrative_id=narrative.narrative_id,
                claim_id=claim.claim_id,
                role=role,
                available_at=now,
                run_id=self.run_id,
            )
        )
        self.session.flush()
        return narrative.node_id

    def _similar_narrative(self, proposition: str) -> Narrative | None:
        target = normalize_text(proposition)
        best, best_score = None, 0.0
        for narrative in self.session.scalars(sa.select(Narrative)):
            score = SequenceMatcher(None, target, normalize_text(narrative.proposition)).ratio()
            if score > best_score:
                best, best_score = narrative, score
        return best if best_score >= NARRATIVE_SIMILARITY else None

    def _create_narrative(
        self, proposition: str, now: datetime, cause: EventCause, claim: Claim
    ) -> Narrative:
        digest = hashlib.sha1(normalize_text(proposition).encode()).hexdigest()[:10]
        node = Node(
            node_id=new_id("nod", now),
            canonical_key=f"NARRATIVE:n-{digest}",
            node_type=NodeType.NARRATIVE,
            label=proposition[:300],
            status=NodeStatus.CANDIDATE,
            created_at=now,
            available_at=now,
            created_run_id=self.run_id,
        )
        self.session.add(node)
        self.session.flush()
        narrative = Narrative(
            narrative_id=new_id("nar", now),
            node_id=node.node_id,
            proposition=proposition,
            state=NarrativeState.EMERGING,
            created_at=now,
            available_at=now,
        )
        self.session.add(narrative)
        self.session.flush()
        doc = self.session.get_one(Document, claim.document_id)
        self._event(
            EventType.NARRATIVE_CREATED,
            cause,
            now,
            doc,
            node_id=node.node_id,
            narrative_id=narrative.narrative_id,
            payload={"proposition": proposition},
        )
        return narrative


def _res_key(r: Resolution) -> str:
    return r.node_id or f"new:{r.new_key}"

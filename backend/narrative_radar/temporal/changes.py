"""두 시점 사이에 "달라진 점" (DECISIONS D11).

새로 관측된 것 / 달라진 기존 이야기 / 그렇게 판단한 근거를 규칙으로 뽑는다. 문장은 화면에서 만든다.

- 모든 계산은 시점별 상태(state.py)와 available_at <= until인 기록만 쓴다.
- 항목마다 변화 원인(새로 관측 / 과거 자료 / 재분류)과 근거 수를 붙인다.
  확산 = 글 수, 독립 = 서로 다른 묶음·작성자.
- 관측 공백(수집기가 멈춘 구간)이 있으면 관심도 하락은 판단하지 않는다 (D10).
- 지워진 글은 근거로 다시 보여주지 않는다 (DATA_POLICY 12).
"""

from dataclasses import dataclass, field
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.db.models import (
    Claim,
    Document,
    EdgeEvidence,
    GraphEvent,
    InterestProfile,
    Narrative,
    NarrativeClaim,
    NodeMention,
    SourceHealth,
)
from narrative_radar.schemas.enums import EdgeType, EventCause, EventType, SourceHealthStatus
from narrative_radar.temporal.narratives import narrative_state_at
from narrative_radar.temporal.state import GraphState, graph_state

ATTENTION_RATIO = 2.0
ATTENTION_MIN_MENTIONS = 5
MAX_EVIDENCE = 3


@dataclass
class EvidenceRef:
    document_id: str
    source: str
    url: str
    published_at: datetime
    excerpt: str | None


@dataclass
class ChangeItem:
    # new_narrative / narrative_shift / new_node / new_relation / attention_up / attention_down
    kind: str
    label: str
    node_ids: list[str]
    cause: str
    spread_documents: int
    independent: int
    available_at: datetime | None
    edge_id: str | None = None
    narrative_id: str | None = None
    detail: dict[str, object] = field(default_factory=dict)
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass
class ObservationGap:
    source_adapter_id: str
    start: datetime
    end: datetime
    status: str
    note: str | None


@dataclass
class ChangeReport:
    since: datetime
    until: datetime
    items: list[ChangeItem]
    gaps: list[ObservationGap]


def _evidence_docs(
    session: Session, doc_ids: list[str], excerpts: dict[str, str]
) -> list[EvidenceRef]:
    if not doc_ids:
        return []
    docs = session.scalars(
        sa.select(Document)
        .where(Document.document_id.in_(doc_ids), Document.deleted_observed_at.is_(None))
        .order_by(Document.published_at.desc())
        .limit(MAX_EVIDENCE)
    ).all()
    return [
        EvidenceRef(
            d.document_id, d.source, d.source_url, d.published_at, excerpts.get(d.document_id)
        )
        for d in docs
    ]


def _node_evidence(session: Session, node_id: str, until: datetime) -> list[EvidenceRef]:
    ids = list(
        session.scalars(
            sa.select(NodeMention.document_id)
            .where(NodeMention.node_id == node_id, NodeMention.available_at <= until)
            .order_by(NodeMention.published_at.desc())
            .limit(10)
        )
    )
    return _evidence_docs(session, ids, {})


def _edge_evidence(session: Session, edge_id: str, until: datetime) -> list[EvidenceRef]:
    rows = session.execute(
        sa.select(EdgeEvidence.document_id, Claim.excerpt)
        .outerjoin(Claim, Claim.claim_id == EdgeEvidence.claim_id)
        .where(EdgeEvidence.edge_id == edge_id, EdgeEvidence.available_at <= until)
    ).all()
    return _evidence_docs(session, [d for d, _ in rows], {d: e for d, e in rows if e})


def _narrative_evidence(session: Session, narrative_id: str, until: datetime) -> list[EvidenceRef]:
    rows = session.execute(
        sa.select(Claim.document_id, Claim.excerpt)
        .join(NarrativeClaim, NarrativeClaim.claim_id == Claim.claim_id)
        .where(NarrativeClaim.narrative_id == narrative_id, NarrativeClaim.available_at <= until)
    ).all()
    return _evidence_docs(session, [d for d, _ in rows], {d: e for d, e in rows if e})


def _cause(
    session: Session, since: datetime, until: datetime, **target: str
) -> tuple[str, datetime | None]:
    column = GraphEvent.node_id if "node_id" in target else GraphEvent.edge_id
    value = target.get("node_id") or target.get("edge_id")
    event = session.scalars(
        sa.select(GraphEvent)
        .where(column == value, GraphEvent.available_at > since, GraphEvent.available_at <= until)
        .order_by(GraphEvent.available_at.desc())
    ).first()
    if event is None:
        return EventCause.OBSERVED_NEW.value, None
    return event.cause.value, event.available_at


def observation_gaps(session: Session, since: datetime, until: datetime) -> list[ObservationGap]:
    rows = session.scalars(
        sa.select(SourceHealth)
        .where(
            SourceHealth.window_end > since,
            SourceHealth.window_start <= until,
            SourceHealth.status != SourceHealthStatus.OK,
        )
        .order_by(SourceHealth.window_start)
    ).all()
    return [
        ObservationGap(r.source_adapter_id, r.window_start, r.window_end, r.status.value, r.note)
        for r in rows
    ]


def what_changed(
    session: Session,
    profile: InterestProfile,
    since: datetime,
    until: datetime,
    viewer_id: str | None = None,
) -> ChangeReport:
    before: GraphState = graph_state(session, profile, since, viewer_id, include_pending=False)
    after: GraphState = graph_state(session, profile, until, viewer_id, include_pending=False)
    before_nodes = {n.node_id: n for n in before.nodes}
    after_nodes = {n.node_id: n for n in after.nodes}
    labels = {n.node_id: n.label for n in after.nodes}
    narrative_of = dict(
        session.execute(
            sa.select(Narrative.node_id, Narrative.narrative_id).where(
                Narrative.node_id.in_(after_nodes)
            )
        ).all()
    )
    items: list[ChangeItem] = []

    # 새로 들어온 노드와 내러티브
    for node_id, node in after_nodes.items():
        if node_id in before_nodes:
            continue
        cause, at = _cause(session, since, until, node_id=node_id)
        if node_id in narrative_of:
            snap = narrative_state_at(session, narrative_of[node_id], until)
            items.append(
                ChangeItem(
                    kind="new_narrative",
                    label=node.label,
                    node_ids=[node_id],
                    cause=cause,
                    spread_documents=node.mentions_7d,
                    independent=snap.supports_recent + snap.contradicts_recent,
                    available_at=at,
                    narrative_id=narrative_of[node_id],
                    detail={
                        "state": snap.state.value if snap.state else None,
                        "supports": snap.supports_recent,
                        "contradicts": snap.contradicts_recent,
                    },
                    evidence=_narrative_evidence(session, narrative_of[node_id], until),
                )
            )
        else:
            items.append(
                ChangeItem(
                    kind="new_node",
                    label=node.label,
                    node_ids=[node_id],
                    cause=cause,
                    spread_documents=node.mentions_7d,
                    independent=node.independent_7d,
                    available_at=at,
                    detail={"node_type": node.node_type, "depth": node.depth},
                    evidence=_node_evidence(session, node_id, until),
                )
            )

    # 달라진 기존 내러티브
    for node_id, narrative_id in narrative_of.items():
        if node_id not in before_nodes:
            continue
        old = narrative_state_at(session, narrative_id, since)
        new = narrative_state_at(session, narrative_id, until)
        if old.state == new.state:
            continue
        items.append(
            ChangeItem(
                kind="narrative_shift",
                label=labels[node_id],
                node_ids=[node_id],
                cause=_cause(session, since, until, node_id=node_id)[0],
                spread_documents=after_nodes[node_id].mentions_7d,
                independent=new.supports_recent + new.contradicts_recent,
                available_at=None,
                narrative_id=narrative_id,
                detail={
                    "from": old.state.value if old.state else None,
                    "to": new.state.value if new.state else None,
                    "supports": new.supports_recent,
                    "contradicts": new.contradicts_recent,
                    "supports_before": old.supports_recent,
                    "contradicts_before": old.contradicts_recent,
                },
                evidence=_narrative_evidence(session, narrative_id, until),
            )
        )

    # 새로 확정된 관계
    confirmed_in_window = set(
        session.scalars(
            sa.select(GraphEvent.edge_id).where(
                GraphEvent.event_type == EventType.EDGE_CONFIRMED,
                GraphEvent.available_at > since,
                GraphEvent.available_at <= until,
            )
        )
    )
    for edge in after.edges:
        if edge.edge_id not in confirmed_in_window or edge.relation == EdgeType.CO_MENTIONED_WITH:
            continue
        if edge.source in narrative_of or edge.target in narrative_of:
            continue  # 내러티브 연결은 내러티브 항목으로 보여준다
        cause, at = _cause(session, since, until, edge_id=edge.edge_id)
        items.append(
            ChangeItem(
                kind="new_relation",
                label=f"{labels.get(edge.source, '?')} → {labels.get(edge.target, '?')}",
                node_ids=[edge.source, edge.target],
                cause=cause,
                spread_documents=edge.evidence_documents,
                independent=edge.independent_evidence,
                available_at=at,
                edge_id=edge.edge_id,
                detail={"relation": edge.relation},
                evidence=_edge_evidence(session, edge.edge_id, until),
            )
        )

    # 관심도 변화 (수집량 대비 비중으로 판단)
    gaps = observation_gaps(session, since, until)
    for node_id, node in after_nodes.items():
        old = before_nodes.get(node_id)
        if old is None or node_id in narrative_of:
            continue
        if node.mentions_7d >= ATTENTION_MIN_MENTIONS and node.share_7d >= ATTENTION_RATIO * max(
            old.share_7d, 1e-9
        ):
            kind = "attention_up"
        elif (
            not gaps
            and old.mentions_7d >= ATTENTION_MIN_MENTIONS
            and node.share_7d * ATTENTION_RATIO <= old.share_7d
        ):
            kind = "attention_down"
        else:
            continue
        items.append(
            ChangeItem(
                kind=kind,
                label=node.label,
                node_ids=[node_id],
                cause=EventCause.OBSERVED_NEW.value,
                spread_documents=node.mentions_7d,
                independent=node.independent_7d,
                available_at=None,
                detail={
                    "share_before": old.share_7d,
                    "share_after": node.share_7d,
                    "mentions_before": old.mentions_7d,
                    "mentions_after": node.mentions_7d,
                },
                evidence=_node_evidence(session, node_id, until),
            )
        )

    order = {
        "new_narrative": 0,
        "narrative_shift": 1,
        "new_node": 2,
        "new_relation": 3,
        "attention_up": 4,
        "attention_down": 5,
    }
    items.sort(key=lambda i: (order[i.kind], -i.independent, -i.spread_documents))
    return ChangeReport(since, until, items, gaps)

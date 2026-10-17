"""시점 t의 그래프 상태 (PRD 10장, DECISIONS D2·D9).

규칙: 시점 t의 상태는 available_at <= t인 기록만으로 계산한다. 그 뒤에 알게 된 것은 쓰지 않는다.

- 노드·관계 상태: 이벤트를 시간순으로 적용해 복원한다.
- 관계 강도: 근거(복사 묶음당 하나)마다 exp(-(t - 게시 시각)/τ)를 더한다. τ = 7일.
- 관심도: 언급마다 exp(-(t - 게시 시각)/τ)를 더한다. τ = 2일. 확산을 보는 값이므로 복사도 센다.
- 휴면: 마지막 언급이 72시간보다 오래되면 휴면으로 표시한다.
- 관심사 그래프: 그 시점까지의 자동 확장 결정 중 마지막 것이 포함(admitted)인 노드 + 루트.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.db.models import (
    Document,
    Edge,
    EdgeEvidence,
    GraphEvent,
    InterestProfile,
    Node,
    NodeMention,
    ProfileNode,
    ViewerOverlay,
)
from narrative_radar.schemas.enums import (
    EdgeStatus,
    EdgeType,
    EventCause,
    EventType,
    NodeStatus,
    ProfileNodeStatus,
    TargetType,
    ViewerDecision,
)

EDGE_TAU = timedelta(days=7)
ACTIVITY_TAU = timedelta(days=2)
DORMANT_AFTER = timedelta(hours=72)
WINDOW = timedelta(days=7)

_NODE_TRANSITIONS = {
    EventType.NODE_ACTIVATED: NodeStatus.ACTIVE,
    EventType.NODE_REACTIVATED: NodeStatus.ACTIVE,
    EventType.NODE_DORMANT: NodeStatus.DORMANT,
    EventType.NODE_REJECTED: NodeStatus.REJECTED,
    EventType.NODE_MERGED: NodeStatus.MERGED,
}
_EDGE_TRANSITIONS = {
    EventType.EDGE_CREATED: EdgeStatus.CANDIDATE,
    EventType.EDGE_CONFIRMED: EdgeStatus.CONFIRMED,
    EventType.EDGE_WEAKENED: EdgeStatus.WEAKENED,
    EventType.EDGE_REJECTED: EdgeStatus.REJECTED,
}


def _decay(age: timedelta, tau: timedelta) -> float:
    return math.exp(-max(age, timedelta(0)) / tau)


@dataclass
class NodeState:
    node_id: str
    canonical_key: str
    label: str
    node_type: str
    status: str
    membership: str  # root / admitted / pending_review
    depth: int | None
    first_seen: datetime
    activity: float
    mentions_7d: int
    independent_7d: int
    share_7d: float
    last_mention_at: datetime | None
    dormant: bool


@dataclass
class EdgeState:
    edge_id: str
    source: str
    target: str
    relation: str
    status: str
    strength: float
    independent_evidence: int
    evidence_documents: int
    first_seen: datetime


@dataclass
class GraphState:
    as_of: datetime
    profile_id: str
    root_node_id: str | None
    nodes: list[NodeState] = field(default_factory=list)
    edges: list[EdgeState] = field(default_factory=list)
    # 관심사가 생기기 전 시점: 그때 공통 그래프로 이 루트를 봤다면 어땠을지 되살린 것 (D7, D23)
    reconstructed: bool = False


def membership_at(
    session: Session, profile: InterestProfile, as_of: datetime
) -> dict[str, tuple[ProfileNodeStatus, int | None]]:
    rows = session.execute(
        sa.select(ProfileNode.node_id, ProfileNode.status, ProfileNode.depth)
        .where(ProfileNode.profile_id == profile.profile_id, ProfileNode.available_at <= as_of)
        .order_by(ProfileNode.available_at, ProfileNode.decision_id)
    ).all()
    latest: dict[str, tuple[ProfileNodeStatus, int | None]] = {}
    for node_id, status, depth in rows:
        latest[node_id] = (status, depth)
    return latest


def reconstructed_membership(
    session: Session, root_node_id: str, as_of: datetime, max_depth: int
) -> dict[str, tuple[ProfileNodeStatus, int | None]]:
    """관심사 결정 이력 없이, 시점 t의 관계 상태만으로 루트 주변을 다시 그린다.

    관측 확정 관계로 닿으면 포함, 발견 후보로만 닿으면 검토 대기. 하루 예산은 적용하지 않는다.
    """
    from narrative_radar.discovery.expansion import shortest_depths

    rows = session.execute(
        sa.select(Edge.edge_id, Edge.source_node_id, Edge.target_node_id).where(
            Edge.available_at <= as_of, Edge.relation_type != EdgeType.CO_MENTIONED_WITH
        )
    ).all()
    status = edge_statuses_at(session, {r[0] for r in rows}, as_of)
    confirmed = [(a, b) for e, a, b in rows if status.get(e) == EdgeStatus.CONFIRMED]
    reachable = [
        (a, b)
        for e, a, b in rows
        if status.get(e, EdgeStatus.CANDIDATE) in (EdgeStatus.CONFIRMED, EdgeStatus.CANDIDATE)
    ]
    members: dict[str, tuple[ProfileNodeStatus, int | None]] = {
        n: (ProfileNodeStatus.ADMITTED, d)
        for n, d in shortest_depths(confirmed, root_node_id, max_depth).items()
    }
    for n, d in shortest_depths(reachable, root_node_id, max_depth).items():
        members.setdefault(n, (ProfileNodeStatus.PENDING_REVIEW, d))
    return members


def node_statuses_at(
    session: Session, node_ids: set[str], as_of: datetime
) -> dict[str, NodeStatus]:
    statuses: dict[str, NodeStatus] = {}
    rows = session.execute(
        sa.select(GraphEvent.node_id, GraphEvent.event_type, GraphEvent.cause)
        .where(
            GraphEvent.node_id.in_(node_ids),
            GraphEvent.edge_id.is_(None),
            GraphEvent.available_at <= as_of,
        )
        .order_by(GraphEvent.available_at, GraphEvent.event_id)
    ).all()
    for node_id, event_type, cause in rows:
        if event_type in (EventType.NODE_CREATED, EventType.NARRATIVE_CREATED):
            # 관심사로 직접 등록한 루트는 처음부터 활성이다
            statuses.setdefault(
                node_id,
                NodeStatus.ACTIVE if cause == EventCause.USER_ACTION else NodeStatus.CANDIDATE,
            )
        elif event_type in _NODE_TRANSITIONS:
            statuses[node_id] = _NODE_TRANSITIONS[event_type]
    return statuses


def edge_statuses_at(
    session: Session, edge_ids: set[str], as_of: datetime
) -> dict[str, EdgeStatus]:
    statuses: dict[str, EdgeStatus] = {}
    rows = session.execute(
        sa.select(GraphEvent.edge_id, GraphEvent.event_type)
        .where(GraphEvent.edge_id.in_(edge_ids), GraphEvent.available_at <= as_of)
        .order_by(GraphEvent.available_at, GraphEvent.event_id)
    ).all()
    for edge_id, event_type in rows:
        if event_type in _EDGE_TRANSITIONS:
            statuses[edge_id] = _EDGE_TRANSITIONS[event_type]
    return statuses


def hidden_for_viewer(session: Session, profile_id: str, viewer_id: str | None) -> set[str]:
    if viewer_id is None:
        return set()
    return set(
        session.scalars(
            sa.select(ViewerOverlay.target_id).where(
                ViewerOverlay.viewer_id == viewer_id,
                ViewerOverlay.profile_id == profile_id,
                ViewerOverlay.target_type == TargetType.NODE,
                ViewerOverlay.decision.in_([ViewerDecision.REJECTED, ViewerDecision.HIDDEN]),
            )
        )
    )


def graph_state(
    session: Session,
    profile: InterestProfile,
    as_of: datetime,
    viewer_id: str | None = None,
    include_pending: bool = True,
) -> GraphState:
    root = session.scalar(sa.select(Node).where(Node.canonical_key == profile.root_canonical_key))
    state = GraphState(as_of, profile.profile_id, root.node_id if root else None)
    state.reconstructed = as_of < profile.created_at
    if root is None or root.available_at > as_of:
        return state

    if state.reconstructed:
        members = reconstructed_membership(session, root.node_id, as_of, profile.max_depth)
    else:
        members = membership_at(session, profile, as_of)
    hidden = hidden_for_viewer(session, profile.profile_id, viewer_id)
    return _fill_state(session, state, root, members, as_of, include_pending, hidden)


def neighborhood_state(session: Session, node: Node, as_of: datetime) -> GraphState:
    """노드 하나와 그 바로 옆(관측 확정·발견 후보 관계) 상태.

    관심사와 무관한 노드 중심 보기다 (위키, 관심사 밖 노드 정보).
    """
    state = GraphState(as_of, "", node.node_id)
    if node.available_at > as_of:
        return state
    members = reconstructed_membership(session, node.node_id, as_of, 1)
    return _fill_state(session, state, node, members, as_of, True, set())


def _fill_state(
    session: Session,
    state: GraphState,
    root: Node,
    members: dict[str, tuple[ProfileNodeStatus, int | None]],
    as_of: datetime,
    include_pending: bool,
    hidden: set[str],
) -> GraphState:
    wanted = {ProfileNodeStatus.ADMITTED} | (
        {ProfileNodeStatus.PENDING_REVIEW} if include_pending else set()
    )
    node_ids = {nid for nid, (status, _) in members.items() if status in wanted}
    node_ids.add(root.node_id)
    node_ids -= hidden

    nodes = {
        n.node_id: n
        for n in session.scalars(
            sa.select(Node).where(Node.node_id.in_(node_ids), Node.available_at <= as_of)
        )
    }
    statuses = node_statuses_at(session, set(nodes), as_of)

    # 관심도와 비중: 최근 7일 처리된 글 전체 대비
    mentions: dict[str, list[tuple[datetime, str | None, str | None]]] = defaultdict(list)
    for node_id, published_at, group, author in session.execute(
        sa.select(
            NodeMention.node_id,
            NodeMention.published_at,
            NodeMention.derivation_group_id,
            NodeMention.author_hash,
        ).where(NodeMention.node_id.in_(nodes), NodeMention.available_at <= as_of)
    ):
        mentions[node_id].append((published_at, group, author))
    total_7d = (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(Document)
            .where(
                Document.available_at <= as_of,
                Document.published_at > as_of - WINDOW,
                Document.published_at <= as_of,
            )
        )
        or 0
    )

    for node_id, node in nodes.items():
        status = statuses.get(node_id, NodeStatus.CANDIDATE)
        if status in (NodeStatus.REJECTED, NodeStatus.MERGED):
            continue
        ms = mentions.get(node_id, [])
        recent = [m for m in ms if as_of - WINDOW < m[0] <= as_of]
        last = max((m[0] for m in ms if m[0] <= as_of), default=None)
        independent = min(
            len({g or f"m{i}" for i, (_, g, _) in enumerate(recent)}),
            len({a or f"m{i}" for i, (_, _, a) in enumerate(recent)}),
        )
        membership = "root" if node_id == root.node_id else members[node_id][0].value
        dormant = node_id != root.node_id and (last is None or as_of - last > DORMANT_AFTER)
        state.nodes.append(
            NodeState(
                node_id=node_id,
                canonical_key=node.canonical_key,
                label=node.label,
                node_type=node.node_type.value,
                status=NodeStatus.DORMANT.value if dormant else status.value,
                membership=membership,
                depth=0 if node_id == root.node_id else members[node_id][1],
                first_seen=node.available_at,
                activity=round(
                    sum(_decay(as_of - p, ACTIVITY_TAU) for p, _, _ in ms if p <= as_of), 4
                ),
                mentions_7d=len(recent),
                independent_7d=independent,
                share_7d=round(len(recent) / total_7d, 4) if total_7d else 0.0,
                last_mention_at=last,
                dormant=dormant,
            )
        )

    visible = {n.node_id for n in state.nodes}
    edges = session.scalars(
        sa.select(Edge).where(
            Edge.source_node_id.in_(visible),
            Edge.target_node_id.in_(visible),
            Edge.available_at <= as_of,
        )
    ).all()
    edge_status = edge_statuses_at(session, {e.edge_id for e in edges}, as_of)
    evidence: dict[str, list[tuple[datetime, str | None, str | None, str]]] = defaultdict(list)
    for edge_id, published_at, group, author, doc_id in session.execute(
        sa.select(
            EdgeEvidence.edge_id,
            Document.published_at,
            EdgeEvidence.derivation_group_id,
            EdgeEvidence.author_hash,
            EdgeEvidence.document_id,
        )
        .join(Document, Document.document_id == EdgeEvidence.document_id)
        .where(
            EdgeEvidence.edge_id.in_([e.edge_id for e in edges]), EdgeEvidence.available_at <= as_of
        )
    ):
        evidence[edge_id].append((published_at, group, author, doc_id))

    for edge in edges:
        status = edge_status.get(edge.edge_id, EdgeStatus.CANDIDATE)
        if status == EdgeStatus.REJECTED:
            continue
        ev = evidence.get(edge.edge_id, [])
        first_per_group: dict[str, datetime] = {}
        for published_at, group, _, doc_id in ev:
            key = group or f"doc:{doc_id}"
            if key not in first_per_group or published_at < first_per_group[key]:
                first_per_group[key] = published_at
        strength = sum(_decay(as_of - p, EDGE_TAU) for p in first_per_group.values() if p <= as_of)
        independent = min(len(first_per_group), len({a or f"doc:{d}" for _, _, a, d in ev}))
        state.edges.append(
            EdgeState(
                edge_id=edge.edge_id,
                source=edge.source_node_id,
                target=edge.target_node_id,
                relation=edge.relation_type.value,
                status=status.value,
                strength=round(strength, 4),
                independent_evidence=independent,
                evidence_documents=len(ev),
                first_seen=edge.available_at,
            )
        )
    state.nodes.sort(key=lambda n: (n.depth if n.depth is not None else 9, -n.activity))
    state.edges.sort(key=lambda e: (e.relation == EdgeType.CO_MENTIONED_WITH.value, -e.strength))
    return state

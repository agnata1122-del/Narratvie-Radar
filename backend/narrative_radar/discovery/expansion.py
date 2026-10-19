"""관심사 그래프 자동 확장 (PRD 8.3, DECISIONS D8).

- 탐색 깊이: 관측 확정된 의미 관계(공동 언급 제외)로 루트에서 잰 최단거리.
- 깊이 안에 들어오면 하루 예산 안에서 포함(admitted)한다.
- 후보 관계로만 닿는 노드, 예산을 넘은 노드, 자동 확장이 꺼진 경우는
  검토 대기(pending_review)로 둔다.
- 결정은 profile_nodes에 이력으로 쌓는다. 같은 결정을 반복해서 쌓지 않는다.
- 확장 경로로 쓰지 않는 관계 (D39): 공동 언급, 모호한 관계(RELATED_TO·BELONGS_TO), 근거가 탐색 가설
  단계인 관계(근거가 모두 추측). 병합된 노드는 병합 대상으로 읽는다.
- 장소 노드는 자동으로 넣지 않고 검토 대기로 둔다 (허브가 되어 가지가 번지는 것을 막는다).
- 같은 깊이에서는 근거 단계(사실 확인 > 반복 관측)와 독립 근거 수가 높은 노드부터 예산을 쓴다.
"""

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.core.clock import Clock
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import Edge, InterestProfile, Node, ProfileNode
from narrative_radar.graph.evidence import TIER_RANK, edge_tiers
from narrative_radar.graph.merge import merge_target_map
from narrative_radar.schemas.enums import (
    EdgeStatus,
    EdgeType,
    EvidenceTier,
    NodeStatus,
    NodeType,
    ProfileNodeStatus,
)

# 확장 경로로 쓰지 않는 관계
NOT_EXPANDING = frozenset({EdgeType.CO_MENTIONED_WITH, EdgeType.RELATED_TO, EdgeType.BELONGS_TO})
# 자동으로 넣지 않는 노드 유형 (검토 대기).
# 주제는 범위가 넓은지 기계로 가를 수 없어 근거 단계로 거른다
REVIEW_NODE_TYPES = frozenset({NodeType.PLACE})


def shortest_depths(edges: Iterable[tuple[str, str]], root: str, max_depth: int) -> dict[str, int]:
    """방향을 무시한 최단거리. max_depth보다 먼 노드는 넣지 않는다."""
    neighbors: dict[str, set[str]] = {}
    for a, b in edges:
        neighbors.setdefault(a, set()).add(b)
        neighbors.setdefault(b, set()).add(a)
    depths = {root: 0}
    queue = deque([root])
    while queue:
        node = queue.popleft()
        if depths[node] >= max_depth:
            continue
        for nxt in neighbors.get(node, ()):
            if nxt not in depths:
                depths[nxt] = depths[node] + 1
                queue.append(nxt)
    return depths


def semantic_edges(session: Session, statuses: Iterable[EdgeStatus]) -> list[tuple[str, str]]:
    return [(a, b) for a, b, _ in expansion_edges(session, statuses)]


def expansion_edges(session: Session, statuses: Iterable[EdgeStatus]) -> list[tuple[str, str, str]]:
    """확장 경로로 쓰는 관계 (출발, 도착, edge_id). 끝점은 병합 대상으로 바꾼다.

    확정 관계는 근거 단계가 탐색 가설이면 뺀다(후보 관계는 원래 검토 대기로만 쓰인다)."""
    narratives = set(
        session.scalars(sa.select(Node.node_id).where(Node.node_type == NodeType.NARRATIVE))
    )
    rows = [
        (a, b, e, st)
        for a, b, e, st, rel in session.execute(
            sa.select(
                Edge.source_node_id,
                Edge.target_node_id,
                Edge.edge_id,
                Edge.status,
                Edge.relation_type,
            ).where(
                Edge.status.in_(list(statuses)),
                Edge.relation_type != EdgeType.CO_MENTIONED_WITH,
            )
        )
        # 내러티브와 개체를 잇는 RELATED_TO는 앱이 만든 연결이라 경로로 쓴다
        if rel not in NOT_EXPANDING or a in narratives or b in narratives
    ]
    confirmed = [e for _, _, e, st in rows if st == EdgeStatus.CONFIRMED]
    tiers = edge_tiers(session, confirmed) if confirmed else {}
    merged = merge_target_map(session)
    out = []
    for a, b, edge_id, st in rows:
        if st == EdgeStatus.CONFIRMED and tiers.get(edge_id) == EvidenceTier.HYPOTHESIS:
            continue
        a, b = merged.get(a, a), merged.get(b, b)
        if a != b:
            out.append((a, b, edge_id))
    return out


def _strength(session: Session, edges: list[tuple[str, str, str]]) -> dict[str, tuple[int, int]]:
    """노드마다 닿는 확정 관계 중 가장 좋은 (근거 단계, 독립 근거 수). 예산을 쓰는 순서에 쓴다."""
    from narrative_radar.graph.builder import independent_evidence

    tiers = edge_tiers(session, [e for _, _, e in edges]) if edges else {}
    best: dict[str, tuple[int, int]] = {}
    for a, b, edge_id in edges:
        score = (TIER_RANK[tiers[edge_id]], independent_evidence(session, edge_id))
        for n in (a, b):
            best[n] = max(best.get(n, (0, 0)), score)
    return best


def latest_decisions(session: Session, profile_id: str) -> dict[str, ProfileNodeStatus]:
    rows = session.execute(
        sa.select(ProfileNode.node_id, ProfileNode.status)
        .where(ProfileNode.profile_id == profile_id)
        .order_by(ProfileNode.available_at, ProfileNode.decision_id)
    ).all()
    return {node_id: status for node_id, status in rows}


@dataclass
class ExpansionReport:
    admitted: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)


def expand_profile(
    session: Session,
    clock: Clock,
    run_id: str,
    profile: InterestProfile,
    ignore_budget: bool = False,
) -> ExpansionReport:
    """ignore_budget: 가지를 처음 만들 때는 이미 확정된 주변을 한 번에 담는다 (D23)."""
    report = ExpansionReport()
    root = session.scalar(sa.select(Node).where(Node.canonical_key == profile.root_canonical_key))
    if root is None:
        return report
    now = clock.now()
    root_id = merge_target_map(session).get(root.node_id, root.node_id)
    confirmed_edges = expansion_edges(session, [EdgeStatus.CONFIRMED])
    confirmed = shortest_depths([(a, b) for a, b, _ in confirmed_edges], root_id, profile.max_depth)
    reachable = shortest_depths(
        semantic_edges(session, [EdgeStatus.CONFIRMED, EdgeStatus.CANDIDATE]),
        root_id,
        profile.max_depth,
    )
    strength = _strength(session, confirmed_edges)
    node_types = dict(session.execute(sa.select(Node.node_id, Node.node_type)).all())
    node_status = dict(session.execute(sa.select(Node.node_id, Node.status)).all())
    decisions = latest_decisions(session, profile.profile_id)

    day_start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    used = (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(ProfileNode)
            .where(
                ProfileNode.profile_id == profile.profile_id,
                ProfileNode.status == ProfileNodeStatus.ADMITTED,
                ProfileNode.available_at >= day_start,
                ProfileNode.available_at < day_start + timedelta(days=1),
                ProfileNode.depth > 0,
            )
        )
        or 0
    )

    def decide(node_id: str, status: ProfileNodeStatus, depth: int | None, reason: str) -> None:
        if decisions.get(node_id) == status:
            return
        session.add(
            ProfileNode(
                decision_id=new_id("pnd", now),
                profile_id=profile.profile_id,
                node_id=node_id,
                status=status,
                depth=depth,
                reason=reason,
                available_at=now,
                run_id=run_id,
            )
        )
        decisions[node_id] = status
        (report.admitted if status == ProfileNodeStatus.ADMITTED else report.pending).append(
            node_id
        )

    created = dict(session.execute(sa.select(Node.node_id, Node.created_at)).all())

    def order(kv: tuple[str, int]) -> tuple:
        rank, evidence = strength.get(kv[0], (0, 0))
        return (kv[1], -rank, -evidence, created.get(kv[0]))

    for node_id, depth in sorted(confirmed.items(), key=order):
        if depth == 0 or decisions.get(node_id) in (
            ProfileNodeStatus.ADMITTED,
            ProfileNodeStatus.EXCLUDED,
        ):
            continue
        if node_status.get(node_id) in (NodeStatus.MERGED, NodeStatus.REJECTED):
            continue
        if node_types.get(node_id) in REVIEW_NODE_TYPES:
            decide(node_id, ProfileNodeStatus.PENDING_REVIEW, depth, "generic node type")
        elif not profile.auto_expand:
            decide(node_id, ProfileNodeStatus.PENDING_REVIEW, depth, "auto expansion is off")
        elif used >= profile.max_new_nodes_per_day and not ignore_budget:
            decide(node_id, ProfileNodeStatus.PENDING_REVIEW, depth, "daily budget exhausted")
        else:
            decide(node_id, ProfileNodeStatus.ADMITTED, depth, f"confirmed path at depth {depth}")
            used += 1

    for node_id, depth in sorted(reachable.items(), key=lambda kv: kv[1]):
        if node_id in confirmed or node_id in decisions:
            continue
        if node_status.get(node_id) in (NodeStatus.MERGED, NodeStatus.REJECTED):
            continue
        decide(
            node_id, ProfileNodeStatus.PENDING_REVIEW, depth, "reachable only via candidate edges"
        )
    session.flush()
    return report

"""관심사 그래프 자동 확장 (PRD 8.3, DECISIONS D8).

- 탐색 깊이: 관측 확정된 의미 관계(공동 언급 제외)로 루트에서 잰 최단거리.
- 깊이 안에 들어오면 하루 예산 안에서 포함(admitted)한다.
- 후보 관계로만 닿는 노드, 예산을 넘은 노드, 자동 확장이 꺼진 경우는
  검토 대기(pending_review)로 둔다.
- 결정은 profile_nodes에 이력으로 쌓는다. 같은 결정을 반복해서 쌓지 않는다.
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
from narrative_radar.schemas.enums import EdgeStatus, EdgeType, ProfileNodeStatus


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
    return [
        (a, b)
        for a, b in session.execute(
            sa.select(Edge.source_node_id, Edge.target_node_id).where(
                Edge.status.in_(list(statuses)),
                Edge.relation_type != EdgeType.CO_MENTIONED_WITH,
            )
        )
    ]


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
    confirmed = shortest_depths(
        semantic_edges(session, [EdgeStatus.CONFIRMED]), root.node_id, profile.max_depth
    )
    reachable = shortest_depths(
        semantic_edges(session, [EdgeStatus.CONFIRMED, EdgeStatus.CANDIDATE]),
        root.node_id,
        profile.max_depth,
    )
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
    for node_id, depth in sorted(confirmed.items(), key=lambda kv: (kv[1], created.get(kv[0]))):
        if depth == 0 or decisions.get(node_id) in (
            ProfileNodeStatus.ADMITTED,
            ProfileNodeStatus.EXCLUDED,
        ):
            continue
        if not profile.auto_expand:
            decide(node_id, ProfileNodeStatus.PENDING_REVIEW, depth, "auto expansion is off")
        elif used >= profile.max_new_nodes_per_day and not ignore_budget:
            decide(node_id, ProfileNodeStatus.PENDING_REVIEW, depth, "daily budget exhausted")
        else:
            decide(node_id, ProfileNodeStatus.ADMITTED, depth, f"confirmed path at depth {depth}")
            used += 1

    for node_id, depth in sorted(reachable.items(), key=lambda kv: kv[1]):
        if node_id in confirmed or node_id in decisions:
            continue
        decide(
            node_id, ProfileNodeStatus.PENDING_REVIEW, depth, "reachable only via candidate edges"
        )
    session.flush()
    return report

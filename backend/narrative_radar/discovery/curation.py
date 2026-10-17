"""소유자가 관심사 트리에 노드를 직접 넣는다 (자동 확장과 별개).

- 노드가 없으면 만들고(활성, 원인 user_action), 있으면 그대로 쓴다.
- 별칭은 같은 노드에 없는 표기만 더한다. 트리의 별칭은 수집 검색어가 된다 (profile_terms).
- 포함 결정은 profile_nodes에 이력으로 쌓는다. 이미 포함돼 있으면 다시 쌓지 않는다.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.core.clock import Clock
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import GraphEvent, InterestProfile, Node, NodeAlias, ProfileNode
from narrative_radar.discovery.expansion import latest_decisions
from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas.enums import (
    AliasOrigin,
    EventCause,
    EventType,
    NodeStatus,
    NodeType,
    ProfileNodeStatus,
)


@dataclass
class AdmitReport:
    canonical_key: str
    node_created: bool = False
    admitted: bool = False
    aliases_added: list[str] = field(default_factory=list)


def admit_node(
    session: Session,
    clock: Clock,
    run_id: str,
    profile: InterestProfile,
    canonical_key: str,
    label: str,
    node_type: NodeType,
    aliases: Sequence[str],
    depth: int,
    reason: str,
) -> AdmitReport:
    now = clock.now()
    report = AdmitReport(canonical_key)
    node = session.scalar(sa.select(Node).where(Node.canonical_key == canonical_key))
    if node is None:
        node = Node(
            node_id=new_id("nod", now),
            canonical_key=canonical_key,
            node_type=node_type,
            label=label,
            status=NodeStatus.ACTIVE,
            created_at=now,
            available_at=now,
            created_run_id=run_id,
        )
        session.add(node)
        session.flush()
        session.add(
            GraphEvent(
                event_id=new_id("evt", now),
                event_type=EventType.NODE_CREATED,
                cause=EventCause.USER_ACTION,
                node_id=node.node_id,
                payload={"reason": reason},
                recorded_at=now,
                available_at=now,
                run_id=run_id,
            )
        )
        report.node_created = True

    existing = set(
        session.scalars(
            sa.select(NodeAlias.alias_normalized).where(NodeAlias.node_id == node.node_id)
        )
    )
    for alias in (label, *aliases):
        key = normalize_text(alias)
        if not key or key in existing:
            continue
        existing.add(key)
        session.add(
            NodeAlias(
                alias_id=new_id("als", now),
                node_id=node.node_id,
                alias=alias.strip(),
                alias_normalized=key,
                origin=AliasOrigin.USER,
                created_at=now,
                available_at=now,
            )
        )
        report.aliases_added.append(alias.strip())

    if latest_decisions(session, profile.profile_id).get(node.node_id) != (
        ProfileNodeStatus.ADMITTED
    ):
        session.add(
            ProfileNode(
                decision_id=new_id("pnd", now),
                profile_id=profile.profile_id,
                node_id=node.node_id,
                status=ProfileNodeStatus.ADMITTED,
                depth=depth,
                reason=reason,
                available_at=now,
                run_id=run_id,
            )
        )
        report.admitted = True
    session.flush()
    return report

"""중복 노드 병합 (DECISIONS D39).

- 병합은 소유자가 정한다. 자동으로 합치지 않는다. `duplicate_candidates`는 후보만 보인다.
- 근거 기록(edge_evidence)은 추가만 하는 표라 관계를 옮기지 않는다. 대신 옛 노드를 `merged`로 두고
  `merged_into_node_id`로 잇는다. 이후 반영은 개체 해석이 병합을 따라가 새 노드로 들어가고,
  자동 확장은 관계 끝점을 병합 대상으로 바꿔 읽는다.
- 옛 노드의 이름·별칭은 새 노드의 별칭이 된다(수집 검색어에도 들어간다).
"""

import re
from collections import defaultdict
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.core.clock import Clock
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import GraphEvent, Node, NodeAlias
from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas.enums import AliasOrigin, EventCause, EventType, NodeStatus


@dataclass
class MergeReport:
    old_key: str
    new_key: str
    aliases_added: list[str]


def merge_target_map(session: Session) -> dict[str, str]:
    """병합된 노드 → 최종 노드. 사슬(A→B→C)도 끝까지 따라간다."""
    direct = dict(
        session.execute(
            sa.select(Node.node_id, Node.merged_into_node_id).where(
                Node.merged_into_node_id.is_not(None)
            )
        ).all()
    )
    out = {}
    for start in direct:
        node, seen = start, set()
        while node in direct and node not in seen:
            seen.add(node)
            node = direct[node]
        out[start] = node
    return out


def merge_nodes(
    session: Session, clock: Clock, run_id: str, old_key: str, new_key: str, reason: str
) -> MergeReport:
    old = session.scalar(sa.select(Node).where(Node.canonical_key == old_key))
    new = session.scalar(sa.select(Node).where(Node.canonical_key == new_key))
    if old is None or new is None:
        raise ValueError(f"unknown node: {old_key if old is None else new_key}")
    if old.node_id == new.node_id:
        raise ValueError("cannot merge a node into itself")
    if merge_target_map(session).get(new.node_id) == old.node_id:
        raise ValueError(f"{new_key} is already merged into {old_key}")
    if old.status == NodeStatus.MERGED:
        raise ValueError(f"{old_key} is already merged")
    now = clock.now()
    have = set(
        session.scalars(
            sa.select(NodeAlias.alias_normalized).where(NodeAlias.node_id == new.node_id)
        )
    )
    names = [
        old.label,
        *session.scalars(sa.select(NodeAlias.alias).where(NodeAlias.node_id == old.node_id)),
    ]
    added = []
    for name in names:
        key = normalize_text(name)
        if not key or key in have:
            continue
        have.add(key)
        session.add(
            NodeAlias(
                alias_id=new_id("als", now),
                node_id=new.node_id,
                alias=name,
                alias_normalized=key,
                origin=AliasOrigin.USER,
                created_at=now,
                available_at=now,
            )
        )
        added.append(name)
    old.status = NodeStatus.MERGED
    old.merged_into_node_id = new.node_id
    session.add(
        GraphEvent(
            event_id=new_id("evt", now),
            event_type=EventType.NODE_MERGED,
            cause=EventCause.USER_ACTION,
            node_id=old.node_id,
            payload={"merged_into": new.node_id, "merged_into_key": new_key, "reason": reason},
            recorded_at=now,
            available_at=now,
            run_id=run_id,
        )
    )
    session.flush()
    return MergeReport(old_key, new_key, added)


def _slug(key: str) -> tuple[str, str]:
    prefix, _, rest = key.partition(":")
    return prefix, re.sub(r"[^a-z0-9]", "", rest.lower())


def duplicate_candidates(session: Session) -> list[list[tuple[str, str]]]:
    """중복일 수 있는 노드 묶음.

    같은 유형에서 키 슬러그가 같거나 한쪽이 다른 쪽으로 시작하는 것, 또는 이름이 같은 것.
    예: TECH:ddr · TECH:ddr5 · TECH:ddr-5.
    같은 대상인지는 소유자가 판단한다(DDR5는 DDR의 한 세대)."""
    nodes = session.execute(
        sa.select(Node.canonical_key, Node.label).where(
            Node.status.not_in([NodeStatus.MERGED, NodeStatus.REJECTED])
        )
    ).all()
    by_prefix: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for key, label in nodes:
        prefix, slug = _slug(key)
        if slug:
            by_prefix[prefix].append((slug, key, label))
    parent = {key: key for key, _ in nodes}

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    for items in by_prefix.values():
        items.sort()
        for i, (slug, key, _) in enumerate(items):
            for other_slug, other_key, _ in items[i + 1 :]:
                if not other_slug.startswith(slug):
                    break
                if len(slug) >= 3:
                    union(key, other_key)
    by_label: dict[str, list[str]] = defaultdict(list)
    for key, label in nodes:
        by_label[normalize_text(label)].append(key)
    for keys in by_label.values():
        for k in keys[1:]:
            union(keys[0], k)
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    labels = dict(nodes)
    for key, _ in nodes:
        groups[find(key)].append((key, labels[key]))
    return sorted((sorted(g) for g in groups.values() if len(g) > 1), key=lambda g: g[0][0])

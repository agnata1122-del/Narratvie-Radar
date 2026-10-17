"""개체 정규화 (DECISIONS D4): canonical key → 별칭 → 유사 표기 → 새 후보."""

from dataclasses import dataclass
from difflib import SequenceMatcher

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.classifiers.ontology import valid_key
from narrative_radar.db.models import Node, NodeAlias
from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas.classification import EntityMention
from narrative_radar.schemas.enums import NodeStatus, NodeType

# 표기 유사도가 이 이상이면 같은 개체로 본다. 짧은 표기는 우연히 비슷하기 쉬워 제외한다.
FUZZY_THRESHOLD = 0.92
FUZZY_MIN_LENGTH = 5


@dataclass(frozen=True)
class Resolution:
    mention: EntityMention
    node_id: str | None  # 기존 노드
    new_key: str | None  # 새로 만들 노드의 키
    method: str  # key / alias / fuzzy / new / rejected
    reason: str | None = None


class EntityResolver:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._aliases: dict[str, str] | None = None

    def _alias_index(self) -> dict[str, str]:
        if self._aliases is None:
            self._aliases = {}
            rows = self.session.execute(
                sa.select(NodeAlias.alias_normalized, NodeAlias.node_id)
                .join(Node, Node.node_id == NodeAlias.node_id)
                .where(Node.status != NodeStatus.REJECTED)
                .order_by(NodeAlias.created_at)
            )
            for alias, node_id in rows:
                self._aliases.setdefault(alias, node_id)
        return self._aliases

    def remember_alias(self, alias_normalized: str, node_id: str) -> None:
        self._alias_index().setdefault(alias_normalized, node_id)

    def follow_merges(self, node_id: str) -> str:
        seen = set()
        while node_id not in seen:
            seen.add(node_id)
            node = self.session.get(Node, node_id)
            if node is None or node.merged_into_node_id is None:
                return node_id
            node_id = node.merged_into_node_id
        return node_id

    def resolve(self, mention: EntityMention) -> Resolution:
        if mention.type == NodeType.NARRATIVE:
            return Resolution(mention, None, None, "rejected", "narrative is not an entity type")
        key = mention.canonical_key
        if key:
            node = self.session.scalar(sa.select(Node).where(Node.canonical_key == key))
            if node is not None and node.status != NodeStatus.REJECTED:
                return Resolution(mention, self.follow_merges(node.node_id), None, "key")

        name = normalize_text(mention.name)
        index = self._alias_index()
        if name in index:
            return Resolution(mention, self.follow_merges(index[name]), None, "alias")
        if len(name) >= FUZZY_MIN_LENGTH:
            best = _closest(name, index)
            if best is not None:
                return Resolution(mention, self.follow_merges(best), None, "fuzzy")

        if key and valid_key(mention.type, key):
            return Resolution(mention, None, key, "new")
        return Resolution(
            mention,
            None,
            None,
            "rejected",
            f"no existing node and no valid key for {mention.name!r}",
        )


def _closest(name: str, index: dict[str, str]) -> str | None:
    """유사도가 기준 이상인 가장 가까운 별칭의 노드. 별칭이 많아도 빠르도록 길이와 빠른 상한으로
    먼저 거른다 (두 길이로 낼 수 있는 최대 유사도 2·짧은쪽/합이 기준보다 낮으면 볼 필요가 없다)."""
    best_score, best_node = FUZZY_THRESHOLD, None
    for alias, node_id in index.items():
        shorter, total = min(len(name), len(alias)), len(name) + len(alias)
        if 2 * shorter / total < best_score:
            continue
        matcher = SequenceMatcher(None, name, alias)
        if matcher.real_quick_ratio() < best_score or matcher.quick_ratio() < best_score:
            continue
        score = matcher.ratio()
        if score >= best_score and (best_node is None or score > best_score):
            best_score, best_node = score, node_id
    return best_node

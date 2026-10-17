"""분류할 때 함께 넘기는 현재 온톨로지와 키 규칙."""

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.db.models import Narrative, Node, NodeAlias
from narrative_radar.domains import DomainPack, valid_key
from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas.enums import NodeStatus, NodeType

# 키 규칙은 도메인 팩이 정한다 (공통 규칙 + 팩 규칙, DECISIONS D22)
__all__ = ["Ontology", "load_ontology", "mentions", "valid_key"]


def mentions(text_normalized: str, name_normalized: str) -> bool:
    """정규화한 글에 정규화한 표기가 나오는가."""
    if not name_normalized:
        return False
    if name_normalized.isascii():
        # 영문 표기는 단어 경계로 찾는다 ("nvda"가 다른 단어 안에 걸리지 않게)
        pattern = rf"(?<![a-z0-9]){re.escape(name_normalized)}(?![a-z0-9])"
        return re.search(pattern, text_normalized) is not None
    return name_normalized in text_normalized


@dataclass(frozen=True)
class OntologyNode:
    canonical_key: str
    label: str
    node_type: str
    aliases: list[str]


@dataclass(frozen=True)
class OntologyNarrative:
    narrative_key: str
    proposition: str
    state: str


@dataclass(frozen=True)
class Ontology:
    nodes: list[OntologyNode]
    narratives: list[OntologyNarrative]

    def to_dict(self, pack: DomainPack) -> dict[str, object]:
        return {
            "nodes": [asdict(n) for n in self.nodes],
            "narratives": [asdict(n) for n in self.narratives],
            "key_rules": pack.key_rules(),
        }

    def matching(self, text: str, limit: int | None = None) -> list[OntologyNode]:
        """글에 이름이나 별칭이 나오는 노드. 분류할 때 기존 노드에 잇는 단서로 쓴다."""
        normalized = normalize_text(text)
        out = []
        for node in self.nodes:
            if any(mentions(normalized, normalize_text(n)) for n in (node.label, *node.aliases)):
                out.append(node)
                if limit is not None and len(out) >= limit:
                    break
        return out

    def only(self, keys: Iterable[str]) -> "Ontology":
        wanted = set(keys)
        return replace(self, nodes=[n for n in self.nodes if n.canonical_key in wanted])


def load_ontology(session: Session) -> Ontology:
    usable = (NodeStatus.ACTIVE, NodeStatus.CANDIDATE, NodeStatus.DORMANT)
    nodes = session.scalars(
        sa.select(Node)
        .where(Node.status.in_(usable), Node.node_type != NodeType.NARRATIVE)
        .order_by(Node.canonical_key)
    ).all()
    aliases: dict[str, list[str]] = {}
    for node_id, alias in session.execute(
        sa.select(NodeAlias.node_id, NodeAlias.alias).order_by(NodeAlias.alias)
    ):
        aliases.setdefault(node_id, []).append(alias)
    narratives = session.execute(
        sa.select(Node.canonical_key, Narrative.proposition, Narrative.state)
        .join(Narrative, Narrative.node_id == Node.node_id)
        .where(Node.status.in_(usable))
        .order_by(Node.canonical_key)
    ).all()
    return Ontology(
        nodes=[
            OntologyNode(n.canonical_key, n.label, n.node_type.value, aliases.get(n.node_id, []))
            for n in nodes
        ],
        narratives=[OntologyNarrative(k, p, s.value) for k, p, s in narratives],
    )

"""분류할 때 함께 넘기는 현재 온톨로지와 키 규칙."""

from dataclasses import asdict, dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.db.models import Narrative, Node, NodeAlias
from narrative_radar.domains import DomainPack, valid_key
from narrative_radar.schemas.enums import NodeStatus, NodeType

# 키 규칙은 도메인 팩이 정한다 (공통 규칙 + 팩 규칙, DECISIONS D22)
__all__ = ["Ontology", "load_ontology", "valid_key"]


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

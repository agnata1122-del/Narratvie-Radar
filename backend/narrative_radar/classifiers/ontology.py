"""분류할 때 함께 넘기는 현재 온톨로지와 키 규칙."""

import re
from dataclasses import asdict, dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.db.models import Narrative, Node, NodeAlias
from narrative_radar.schemas.enums import NodeStatus, NodeType

# canonical_key 형식. 기업은 국가:티커, 나머지는 유형:영문 슬러그.
KEY_PATTERNS: dict[NodeType, re.Pattern[str]] = {
    NodeType.COMPANY: re.compile(
        r"^(?:[A-Z]{2}:[A-Z0-9.\-]{1,12}|COMPANY:[a-z0-9]+(?:-[a-z0-9]+)*)$"
    ),
    NodeType.INDUSTRY: re.compile(r"^INDUSTRY:[a-z0-9]+(?:-[a-z0-9]+)*$"),
    NodeType.TECHNOLOGY: re.compile(r"^TECH:[a-z0-9]+(?:-[a-z0-9]+)*$"),
    NodeType.TOPIC: re.compile(r"^TOPIC:[a-z0-9]+(?:-[a-z0-9]+)*$"),
    NodeType.EVENT: re.compile(r"^EVENT:[a-z0-9]+(?:-[a-z0-9]+)*$"),
    NodeType.NARRATIVE: re.compile(r"^NARRATIVE:[a-z0-9]+(?:-[a-z0-9]+)*$"),
}

KEY_EXAMPLES: dict[NodeType, str] = {
    NodeType.COMPANY: "US:NVDA, KR:000660, COMPANY:openai (티커가 없을 때)",
    NodeType.INDUSTRY: "INDUSTRY:semiconductors",
    NodeType.TECHNOLOGY: "TECH:hbm",
    NodeType.TOPIC: "TOPIC:data-center-power",
    NodeType.EVENT: "EVENT:q3-2026-earnings",
    NodeType.NARRATIVE: "NARRATIVE:power-is-the-bottleneck (앱이 만든다)",
}


def valid_key(node_type: NodeType, key: str) -> bool:
    return bool(KEY_PATTERNS[node_type].match(key))


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

    def to_dict(self) -> dict[str, object]:
        return {
            "nodes": [asdict(n) for n in self.nodes],
            "narratives": [asdict(n) for n in self.narratives],
            "key_rules": {t.value: KEY_EXAMPLES[t] for t in NodeType},
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

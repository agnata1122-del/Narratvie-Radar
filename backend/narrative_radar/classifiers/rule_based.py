"""규칙 기반 기준 분류기. 온톨로지 별칭이 본문에 나오는 개체만 찾고 주장은 만들지 않는다.

세션 분류와 비교하는 기준선이며, 테스트에서 LLM 없이 파이프라인을 돌리는 데 쓴다.
"""

from narrative_radar.classifiers.ontology import Ontology, mentions
from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas.classification import ClassificationOutput, EntityMention
from narrative_radar.schemas.enums import NodeType, Stance

MODEL_LABEL = "rule-based.v1"


def classify(text: str, ontology: Ontology, root_key: str) -> ClassificationOutput:
    normalized = normalize_text(text)
    entities: list[EntityMention] = []
    for node in ontology.nodes:
        names = [node.label, *node.aliases]
        hit = next((n for n in names if mentions(normalized, normalize_text(n))), None)
        if hit is not None:
            entities.append(
                EntityMention(
                    name=hit, type=NodeType(node.node_type), canonical_key=node.canonical_key
                )
            )
    keys = {e.canonical_key for e in entities}
    relevance = 1.0 if root_key in keys else (0.5 if entities else 0.0)
    return ClassificationOutput(
        relevance=relevance,
        is_noise=not entities,
        entities=entities[:20],
        stance=Stance.NEUTRAL,
        claims=[],
        needs_review=False,
    )

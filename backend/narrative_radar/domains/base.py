import re
from dataclasses import dataclass, field
from pathlib import Path

from narrative_radar.schemas.enums import NodeType

SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"

# 어느 분야에서나 쓰는 키: 유형 접두사 + 영문 슬러그
CORE_KEY_PREFIX: dict[NodeType, str] = {
    NodeType.ORGANIZATION: "ORG",
    NodeType.PERSON: "PERSON",
    NodeType.PRODUCT: "PRODUCT",
    NodeType.TECHNOLOGY: "TECH",
    NodeType.TOPIC: "TOPIC",
    NodeType.EVENT: "EVENT",
    NodeType.PLACE: "PLACE",
    NodeType.NARRATIVE: "NARRATIVE",
}

CORE_KEY_PATTERNS: dict[NodeType, re.Pattern[str]] = {
    t: re.compile(rf"^{prefix}:{SLUG}$") for t, prefix in CORE_KEY_PREFIX.items()
}

CORE_KEY_EXAMPLES: dict[NodeType, str] = {
    NodeType.ORGANIZATION: "ORG:openai, ORG:krafton",
    NodeType.PERSON: "PERSON:jensen-huang",
    NodeType.PRODUCT: "PRODUCT:gpt-5, PRODUCT:battlegrounds",
    NodeType.TECHNOLOGY: "TECH:hbm",
    NodeType.TOPIC: "TOPIC:data-center-power",
    NodeType.EVENT: "EVENT:q3-2026-earnings",
    NodeType.PLACE: "PLACE:taiwan",
    NodeType.NARRATIVE: "NARRATIVE:power-is-the-bottleneck (앱이 만든다)",
}


@dataclass(frozen=True)
class DomainPack:
    """분야별 설정. 공통 엔진은 이 값을 읽기만 한다."""

    id: str
    name: str
    version: str
    description: str
    # 공통 키 규칙에 더해 이 분야에서 쓰는 키 형식 (예: 금융의 국가:티커)
    extra_key_patterns: dict[NodeType, tuple[str, ...]] = field(default_factory=dict)
    extra_key_examples: dict[NodeType, str] = field(default_factory=dict)
    # 분류 지침 보충 (공통 지침 뒤에 읽는다)
    guideline: Path | None = None
    # 이 분야에 맞는 소스 (등록부의 소스 ID). 비어 있으면 공통 소스만 쓴다.
    sources: tuple[str, ...] = ()
    # 공통 엔진 위에 얹는 선택 기능 (예: 금융의 가격 겹쳐 보기, 섀도 트레이딩)
    lenses: tuple[str, ...] = ()

    def key_rules(self) -> dict[str, str]:
        """분류 세션에 넘기는 유형별 키 예시 (공통 + 이 팩)."""
        rules = {}
        for t in NodeType:
            parts = [CORE_KEY_EXAMPLES[t]]
            if t in self.extra_key_examples:
                parts.insert(0, self.extra_key_examples[t])
            rules[t.value] = " | ".join(parts)
        return rules


def all_key_patterns(packs: "tuple[DomainPack, ...]") -> dict[NodeType, list[re.Pattern[str]]]:
    patterns: dict[NodeType, list[re.Pattern[str]]] = {t: [p] for t, p in CORE_KEY_PATTERNS.items()}
    for pack in packs:
        for t, extra in pack.extra_key_patterns.items():
            patterns[t].extend(re.compile(x) for x in extra)
    return patterns


def valid_key(node_type: NodeType, key: str) -> bool:
    """공통 그래프는 모든 팩이 공유하므로, 등록된 어느 팩의 키 형식이든 받는다.

    같은 개체가 팩마다 다른 키로 생기지 않도록, 분류 지침은 기존 키·별칭을 먼저 쓰게 한다.
    """
    from narrative_radar.domains.registry import PACKS

    return any(p.match(key) for p in all_key_patterns(PACKS)[node_type])

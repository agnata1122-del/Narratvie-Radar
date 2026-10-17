"""도메인 팩 (DECISIONS D22).

공통 엔진(수집 → 분류 → 그래프 → 시간 → 위키 → 화면)은 분야를 모른다.
분야마다 다른 것만 팩에 둔다: 키 규칙, 분류 지침 보충, 추천 소스, 선택 렌즈.
"""

from narrative_radar.domains.base import CORE_KEY_PATTERNS, DomainPack, all_key_patterns, valid_key
from narrative_radar.domains.registry import PACKS, get_pack, pack_for_profiles

__all__ = [
    "CORE_KEY_PATTERNS",
    "PACKS",
    "DomainPack",
    "all_key_patterns",
    "get_pack",
    "pack_for_profiles",
    "valid_key",
]

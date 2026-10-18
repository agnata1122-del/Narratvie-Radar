from collections.abc import Iterable
from pathlib import Path

from narrative_radar.domains.base import SLUG, DomainPack
from narrative_radar.schemas.enums import NodeType

GUIDELINES = Path(__file__).parent.parent / "classifiers" / "guidelines" / "domains"

GENERAL = DomainPack(
    id="general",
    name="일반",
    version="general.v1",
    description="분야를 가리지 않는 기본 설정. 공통 키 규칙과 공통 지침만 쓴다.",
)

FINANCE = DomainPack(
    id="finance",
    name="금융·투자",
    version="finance.v2",
    description="상장사·산업 키, 투자 커뮤니티 은어, 가격 겹쳐 보기·섀도 트레이딩 렌즈.",
    extra_key_patterns={
        # 상장사는 국가:티커. 예전 키(COMPANY:슬러그)도 읽는다.
        NodeType.ORGANIZATION: (r"^[A-Z]{2}:[A-Z0-9.\-]{1,12}$", rf"^COMPANY:{SLUG}$"),
        NodeType.TOPIC: (rf"^INDUSTRY:{SLUG}$",),
    },
    extra_key_examples={
        NodeType.ORGANIZATION: "상장사는 국가:티커 (US:NVDA, KR:000660)",
        NodeType.TOPIC: "산업은 INDUSTRY:semiconductors",
    },
    guideline=GUIDELINES / "finance.md",
    sources=(
        "bluesky_jetstream",
        "hackernews",
        "reddit_arctic",
        "dcinside_stockus",
        "naver_world_nvda",
    ),
    lenses=("price_overlay", "shadow_trading"),
)

PACKS: tuple[DomainPack, ...] = (GENERAL, FINANCE)
_BY_ID = {p.id: p for p in PACKS}


def get_pack(pack_id: str) -> DomainPack:
    try:
        return _BY_ID[pack_id]
    except KeyError:
        raise ValueError(f"unknown domain pack: {pack_id!r} (known: {sorted(_BY_ID)})") from None


def pack_for_profiles(domains: Iterable[str]) -> DomainPack:
    """관심사들이 쓰는 팩이 하나면 그 팩. 여럿이면 어느 팩으로 분류할지 직접 정해야 한다."""
    unique = sorted(set(domains))
    if not unique:
        return GENERAL
    if len(unique) > 1:
        raise ValueError(f"profiles use several domain packs {unique}; pass --domain")
    return get_pack(unique[0])

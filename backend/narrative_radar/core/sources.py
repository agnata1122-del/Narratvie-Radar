"""기본 데이터 소스 등록부.

라이브 수집은 기본값이 꺼짐이다. 켜는 조건과 안전장치는 docs/DATA_POLICY.md에 있다.
"""

from dataclasses import dataclass
from enum import StrEnum


class SourceAccessStatus(StrEnum):
    NOT_AUTHORIZED = "not_authorized"  # 어댑터는 있지만 수집하지 않음
    TEST_MODE = "test_mode"  # 수동 import 등 테스트 데이터만
    LIVE = "live"  # 라이브 수집 중
    PAUSED = "paused"  # 사람이 멈춤
    BLOCKED = "blocked"  # 차단 신호를 감지해 자동 중단됨. 사람이 확인 후 해제


class SourceKind(StrEnum):
    COMMUNITY = "community"
    MARKET = "market"
    OFFICIAL = "official"


@dataclass(frozen=True)
class SourceDefinition:
    id: str
    source: str
    kind: SourceKind
    display_name: str
    base_url: str


DEFAULT_SOURCES: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        id="dcinside_stockus",
        source="dcinside",
        kind=SourceKind.COMMUNITY,
        display_name="미주갤",
        base_url="https://gall.dcinside.com",
    ),
    SourceDefinition(
        id="naver_world_nvda",
        source="naver",
        kind=SourceKind.COMMUNITY,
        display_name="네이버 해외주식 토론",
        base_url="https://m.stock.naver.com",
    ),
)

"""기본 데이터 소스 등록부.

라이브 수집은 기본값이 꺼짐이다. 켜는 조건과 안전장치는 docs/DATA_POLICY.md에 있다.
"""

from dataclasses import dataclass

from narrative_radar.schemas.enums import SourceKind


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

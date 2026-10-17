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
    # 이 소스가 맞는 도메인 팩. 비어 있으면 어느 분야에서나 쓰는 공통 소스다 (DECISIONS D22)
    domains: tuple[str, ...] = ()


DEFAULT_SOURCES: tuple[SourceDefinition, ...] = (
    # 공식 API가 있는 소스 (DECISIONS D15)
    SourceDefinition(
        id="bluesky_jetstream",
        source="bluesky",
        kind=SourceKind.COMMUNITY,
        display_name="Bluesky",
        base_url="wss://jetstream2.us-east.bsky.network",
    ),
    SourceDefinition(
        id="hackernews",
        source="hackernews",
        kind=SourceKind.COMMUNITY,
        display_name="Hacker News",
        base_url="https://hn.algolia.com",
    ),
    # 공식 경로가 없는 소스. 데이터 이용 문의 중 (DATA_POLICY 1–2)
    SourceDefinition(
        id="dcinside_stockus",
        source="dcinside",
        kind=SourceKind.COMMUNITY,
        display_name="미주갤",
        base_url="https://gall.dcinside.com",
        domains=("finance",),
    ),
    SourceDefinition(
        id="naver_world_nvda",
        source="naver",
        kind=SourceKind.COMMUNITY,
        display_name="네이버 해외주식 토론",
        base_url="https://m.stock.naver.com",
        domains=("finance",),
    ),
)

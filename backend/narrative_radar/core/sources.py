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
    # Bluesky 지표 재방문(공개 AppView). 스트림과 다른 서비스라 따로 멈추고 따로 다시 켠다.
    # 글은 bluesky_jetstream으로 저장되고, 이 소스는 중단·상태 기록에만 쓴다.
    SourceDefinition(
        id="bluesky_appview",
        source="bluesky",
        kind=SourceKind.COMMUNITY,
        display_name="Bluesky 지표 (AppView)",
        base_url="https://public.api.bsky.app",
    ),
    SourceDefinition(
        id="hackernews",
        source="hackernews",
        kind=SourceKind.COMMUNITY,
        display_name="Hacker News",
        base_url="https://hn.algolia.com",
    ),
    # 주제 기반 광역 수집 (DECISIONS D24·D25)
    SourceDefinition(
        id="gdelt",
        source="gdelt",
        kind=SourceKind.NEWS,
        display_name="GDELT (뉴스 발견)",
        base_url="https://api.gdeltproject.org",
    ),
    SourceDefinition(
        id="web",
        source="web",
        kind=SourceKind.WEB,
        display_name="웹 (범용 수집)",
        base_url="",
    ),
    # 시세 (DECISIONS D27). 토스증권 웹이 로그인 없이 쓰는 비공식 조회 API: 미국·한국 일봉
    SourceDefinition(
        id="toss_prices",
        source="tossinvest",
        kind=SourceKind.MARKET,
        display_name="토스증권 시세 (웹)",
        base_url="https://wts-info-api.tossinvest.com",
        domains=("finance",),
    ),
    # Reddit 보관본 (DECISIONS D31). Reddit 허락은 확인되지 않음: 원문은 unverified
    SourceDefinition(
        id="reddit_arctic",
        source="reddit",
        kind=SourceKind.COMMUNITY,
        display_name="Reddit (Arctic Shift 보관본)",
        base_url="https://arctic-shift.photon-reddit.com",
        domains=("finance",),
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

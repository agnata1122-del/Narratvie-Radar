from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수(`NR_` 접두사) 또는 `.env`에서 읽는 설정."""

    model_config = SettingsConfigDict(env_prefix="NR_", env_file=".env", extra="ignore")

    db_path: Path = Path("data/narrative_radar.db")

    # 전체 라이브 수집 스위치. 소스별 live_enabled보다 우선한다 (DATA_POLICY.md).
    live_collection_enabled: bool = False

    # 작성자 식별자는 원문을 저장하지 않고 이 비밀값으로 HMAC한 결과만 저장한다.
    author_hash_salt: SecretStr | None = None

    user_agent: str = "NarrativeRadar/0.2 (+https://github.com/agnata1122-del/Narratvie-Radar)"

    # 관측이 게시보다 이만큼 늦으면 실시간으로 본 것이 아니므로 backfill로 표시한다 (DECISIONS D2).
    # 세션을 주기적으로 띄워 수집할 때는 주기보다 조금 길게 잡는다 (DECISIONS D16, OPERATIONS.md).
    backfill_after_minutes: int = 10

    # 새 글의 지표를 다시 읽는 시점(분). 수집 주기가 길면 앞쪽 시점은 다음 실행 때 읽힌다.
    revisit_offsets_minutes: tuple[int, ...] = (10, 60, 360, 1440)
    # 수집 검색어 상한 (DECISIONS D23). 가지가 늘어도 검색어가 끝없이 늘지 않게 한다.
    # Bluesky는 스트림을 받아 여기서 거르므로 넉넉하게, HN은 검색어마다 요청이 늘어 작게 둔다.
    max_search_terms: int = 60
    max_hn_terms: int = 12
    # 주제 기반 발견 (D24). GDELT는 5초에 한 번 넘게 부르면 429를 준다.
    gdelt_min_interval_seconds: float = 6.0
    gdelt_max_records: int = 75
    discovery_max_queries: int = 20  # 한 번 실행에서 부르는 검색 수 (탐색 루트들이 나눠 쓴다)
    discovery_max_candidates: int = 300  # 한 번 실행에서 새로 등록하는 후보 수
    discovery_max_per_domain: int = 10  # 한 번 실행에서 한 사이트가 차지할 수 있는 후보 수
    discovery_first_lookback_hours: int = 24  # 처음 검색하는 노드는 이만큼 거슬러 올라간다
    # GDELT는 15분마다 갱신되어 처음 본 시각이 늘 조금 늦다. 이보다 늦게 본 글만 backfill로 둔다.
    discovery_late_minutes: int = 90
    # 범용 수집기 (D25)
    web_max_pages_per_run: int = 40
    web_min_interval_seconds: float = 10.0  # 같은 사이트에 다시 요청하기까지
    web_max_bytes: int = 2_000_000
    web_max_redirects: int = 3
    web_transient_retries: int = 2  # 같은 후보에 일시 오류가 이만큼 넘으면 실패로 둔다
    web_breaker_transient_limit: int = 5  # 한 사이트에서 일시 오류가 연달아 이만큼이면 차단기 작동

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

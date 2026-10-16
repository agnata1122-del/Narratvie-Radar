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

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

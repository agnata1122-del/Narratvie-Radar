from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수(`NR_` 접두사) 또는 `.env`에서 읽는 설정.

    `ANTHROPIC_API_KEY`는 Anthropic SDK가 직접 읽으므로 여기 두지 않는다.
    """

    model_config = SettingsConfigDict(env_prefix="NR_", env_file=".env", extra="ignore")

    db_path: Path = Path("data/narrative_radar.db")

    # 전체 라이브 수집 스위치. 소스별 live_enabled보다 우선한다 (DATA_POLICY.md).
    live_collection_enabled: bool = False

    # 작성자 식별자는 원문을 저장하지 않고 이 비밀값으로 HMAC한 결과만 저장한다.
    author_hash_salt: SecretStr | None = None

    classifier_model: str = "claude-haiku-5-5"

    user_agent: str = "NarrativeRadar/0.2 (+https://github.com/agnata1122-del/Narratvie-Radar)"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

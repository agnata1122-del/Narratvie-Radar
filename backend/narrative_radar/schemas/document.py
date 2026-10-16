"""수집 어댑터가 내놓는 표준 문서 (PRD 5.2).

작성자 원문 식별자는 받지 않는다. 어댑터는 HMAC 결과(64자리 hex)만 넘길 수 있다 (DATA_POLICY 7).
"""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from narrative_radar.schemas.enums import ContentAccessStatus, IngestMode

AUTHOR_HASH_PATTERN = r"^[0-9a-f]{64}$"


class MetricsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment_count: int | None = Field(default=None, ge=0)
    view_count: int | None = Field(default=None, ge=0)
    upvote_count: int | None = Field(default=None, ge=0)
    downvote_count: int | None = Field(default=None, ge=0)


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=128)
    parent_external_id: str | None = None
    author_hash: str | None = Field(default=None, pattern=AUTHOR_HASH_PATTERN)
    body_text: str
    published_at: AwareDatetime | None = None


class DocumentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_adapter_id: str = Field(min_length=1, max_length=64)
    external_id: str = Field(min_length=1, max_length=128)
    source_url: str = Field(pattern=r"^https?://", max_length=1000)
    title: str
    body_text: str | None = None
    author_hash: str | None = Field(default=None, pattern=AUTHOR_HASH_PATTERN)
    published_at: AwareDatetime
    observed_at: AwareDatetime
    content_access_status: ContentAccessStatus
    ingest_mode: IngestMode
    metrics: MetricsIn | None = None
    comments: list[CommentIn] = Field(default_factory=list)

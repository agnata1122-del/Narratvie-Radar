"""LLM 분류 출력 (PRD 6.3). 이 출력은 바로 반영되지 않고 앱이 검증한 뒤 반영한다 (PRD 4.1)."""

from pydantic import BaseModel, ConfigDict, Field

from narrative_radar.schemas.enums import EdgeType, EvidenceStatus, NodeType, Polarity, Stance

SCHEMA_VERSION = "classification.v1"


class EntityMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="원문에 나온 표기")
    type: NodeType
    canonical_key: str | None = Field(
        default=None, description="기존 노드 목록에서 고른 키. 해당 없으면 null"
    )


class ClaimExtract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    predicate: EdgeType
    object: str
    polarity: Polarity
    stance: Stance
    evidence_status: EvidenceStatus
    excerpt: str = Field(max_length=200, description="주장이 드러난 원문 일부")


class ClassificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevance: float = Field(
        ge=0, le=1, description="관심사와의 관련성. 모델 출력 지표이며 보정된 확률이 아니다"
    )
    is_noise: bool
    entities: list[EntityMention]
    topics: list[str]
    stance: Stance
    claims: list[ClaimExtract]
    needs_review: bool = Field(description="판단이 불확실하면 true. 억지로 분류하지 않는다")
    review_reason: str | None = None

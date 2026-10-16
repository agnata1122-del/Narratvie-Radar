"""분류 출력 (PRD 6.3). 이 출력은 바로 반영되지 않고 앱이 검증한 뒤 반영한다 (PRD 4.1).

분류는 Claude Code 세션이 지침(classifiers/guidelines/classification_v1.md)에 따라 하거나,
규칙 기반 기준 분류기가 한다 (DECISIONS D16).
"""

from pydantic import BaseModel, ConfigDict, Field

from narrative_radar.schemas.enums import (
    EdgeType,
    EvidenceStatus,
    NarrativeRole,
    NodeType,
    Polarity,
    Stance,
)

SCHEMA_VERSION = "classification.v1"

# 글 하나에서 뽑는 양의 상한. 넘으면 분류가 과도하다고 보고 검증에서 거부한다.
MAX_ENTITIES = 20
MAX_CLAIMS = 8


class EntityMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200, description="원문에 나온 표기")
    type: NodeType
    canonical_key: str | None = Field(
        default=None,
        max_length=200,
        description="온톨로지에 있는 키를 고른다. 없으면 규칙에 맞는 새 키를 제안한다",
    )


class ClaimExtract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=200, description="entities의 name 중 하나")
    predicate: EdgeType
    object: str = Field(min_length=1, max_length=200, description="entities의 name 중 하나")
    polarity: Polarity
    stance: Stance
    evidence_status: EvidenceStatus
    excerpt: str = Field(min_length=1, max_length=200, description="주장이 드러난 원문 그대로")
    narrative_key: str | None = Field(
        default=None, max_length=200, description="온톨로지의 내러티브 키. 해당 없으면 null"
    )
    narrative_proposition: str | None = Field(
        default=None,
        max_length=300,
        description="기존 내러티브에 맞지 않을 때 새 내러티브의 핵심 명제 한 문장",
    )
    narrative_role: NarrativeRole | None = Field(
        default=None, description="이 주장이 내러티브를 지지하는지 반박하는지"
    )


class ClassificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevance: float = Field(
        ge=0, le=1, description="관심사와의 관련성. 모델 출력 지표이며 보정된 확률이 아니다"
    )
    is_noise: bool = Field(description="잡담·광고·밈처럼 분석할 내용이 없으면 true")
    language: str | None = Field(default=None, max_length=8, description="ISO 639-1")
    entities: list[EntityMention] = Field(max_length=MAX_ENTITIES)
    stance: Stance
    claims: list[ClaimExtract] = Field(max_length=MAX_CLAIMS)
    needs_review: bool = Field(description="판단이 불확실하면 true. 억지로 분류하지 않는다")
    review_reason: str | None = Field(default=None, max_length=300)


class ClassificationRecord(BaseModel):
    """세션이 돌려주는 한 줄: 어느 문서의 어느 내용 버전을 분류했는지 + 출력."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output: ClassificationOutput

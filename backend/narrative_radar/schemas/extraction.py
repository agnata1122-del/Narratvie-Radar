"""추출 규약 v3 출력 (DECISIONS D38, R1-X 채택).

v2(`classification.py`)는 개체 간 관계만 담았다. v3는 사건(개체의 상태 변화)과 사건 사이 인과 연결,
닫힌 관계 목록을 따로 담고, 별도 대화의 근거 검증 판정(`grounding`)을 함께 저장한다.

그래프 구조는 바꾸지 않는다. 반영할 때 `graph_view()`가 근거 검증을 통과한 항목만 v2 형식의
관계로 바꿔 넘긴다. 사건 정보는 분류 기록(`classification_runs.output`)에 남는다.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas.classification import (
    MAX_CLAIMS as GRAPH_MAX_CLAIMS,
)
from narrative_radar.schemas.classification import (
    MAX_ENTITIES,
    ClaimExtract,
    ClassificationOutput,
    EntityMention,
    PolarityField,
    StanceField,
)
from narrative_radar.schemas.enums import EdgeType, EvidenceStatus, Polarity, Stance

SCHEMA_VERSION = "extraction.v3"

MAX_EVENTS = 16
MAX_CAUSAL_LINKS = 12
MAX_CLAIMS = 8


class Variable(StrEnum):
    # 양 변수
    PRODUCTION_VOLUME = "production_volume"
    PRODUCTION_CAPACITY = "production_capacity"
    SUPPLY = "supply"
    DEMAND = "demand"
    PRICE = "price"
    COST = "cost"
    REVENUE = "revenue"
    PROFIT = "profit"
    MARGIN = "margin"
    INVESTMENT = "investment"
    MARKET_SHARE = "market_share"
    # 상태 변수
    REGULATION = "regulation"
    BUSINESS_STATUS = "business_status"
    QUALIFICATION = "qualification"
    CONTRACT = "contract"
    SHIPMENT = "shipment"
    DELIVERY = "delivery"


STATE_VARIABLES = frozenset(
    {
        Variable.REGULATION,
        Variable.BUSINESS_STATUS,
        Variable.QUALIFICATION,
        Variable.CONTRACT,
        Variable.SHIPMENT,
        Variable.DELIVERY,
    }
)


class Direction(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    UNCHANGED = "unchanged"
    START = "start"
    END = "end"
    COMPLETE = "complete"


QUANTITY_DIRECTIONS = frozenset({Direction.INCREASE, Direction.DECREASE, Direction.UNCHANGED})


class Modality(StrEnum):
    ACTUAL = "actual"
    EXPECTED = "expected"
    CONDITIONAL = "conditional"


class Attribution(StrEnum):
    AUTHOR = "author"
    REPORTED = "reported"
    OFFICIAL = "official"


class EvidenceLevel(StrEnum):
    MECHANISM = "mechanism"
    ASSERTED = "asserted"
    SPECULATIVE = "speculative"


class Verdict(StrEnum):
    ENTAILED = "entailed"
    PARTIAL = "partial"
    NOT_ENTAILED = "not_entailed"


# v3에서 쓰는 관계. CLAIMED_CAUSE_OF·RELATED_TO는 쓰지 않는다 (인과는 causal_links로)
V3_PREDICATES = frozenset(
    {
        EdgeType.SUPPLIES_TO,
        EdgeType.COMPETES_WITH,
        EdgeType.PART_OF,
        EdgeType.BELONGS_TO,
        EdgeType.AFFECTS,
    }
)
# 근거 검증을 통과했을 때 그래프 관계로 넘기는 인과 근거 수준
GRAPH_EVIDENCE_LEVELS = frozenset({EvidenceLevel.MECHANISM, EvidenceLevel.ASSERTED})

_EVIDENCE = {
    Attribution.AUTHOR: EvidenceStatus.COMMUNITY_OPINION,
    Attribution.REPORTED: EvidenceStatus.REPORTED_FACT,
    Attribution.OFFICIAL: EvidenceStatus.OFFICIAL_SOURCE,
}


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=16)
    entity: str = Field(min_length=1, max_length=200, description="entities의 name 중 하나")
    variable: Variable
    direction: Direction
    modality: Modality
    negated: bool = False
    attribution: Attribution
    counterparty: str | None = Field(default=None, max_length=200)
    product: str | None = Field(default=None, max_length=200)
    excerpt: str = Field(min_length=1, max_length=200)


class CausalLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cause: str = Field(min_length=1, max_length=16)
    effect: str = Field(min_length=1, max_length=16)
    evidence_level: EvidenceLevel
    signal: str | None = Field(default=None, max_length=100)
    condition: str | None = Field(default=None, max_length=200)
    excerpt: str = Field(min_length=1, max_length=200)


class ClaimV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=200)
    predicate: EdgeType
    object: str = Field(min_length=1, max_length=200)
    polarity: PolarityField
    modality: Modality
    negated: bool = False
    attribution: Attribution
    excerpt: str = Field(min_length=1, max_length=200)


class GroundingVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^(event|causal_link|claim)$")
    index: int = Field(ge=0)
    verdict: Verdict
    issue: str | None = Field(default=None, max_length=40)
    note: str = Field(default="", max_length=500)


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevance: float = Field(ge=0, le=1)
    is_noise: bool
    language: str | None = Field(default=None, max_length=8)
    entities: list[EntityMention] = Field(max_length=MAX_ENTITIES)
    stance: StanceField = Field(description="작성자의 관심사 루트에 대한 태도 (D35)")
    events: list[Event] = Field(default_factory=list, max_length=MAX_EVENTS)
    causal_links: list[CausalLink] = Field(default_factory=list, max_length=MAX_CAUSAL_LINKS)
    claims: list[ClaimV3] = Field(default_factory=list, max_length=MAX_CLAIMS)
    needs_review: bool
    review_reason: str | None = Field(default=None, max_length=300)
    # 근거 검증 판정. ingest 때 별도 파일에서 붙인다 (모델이 직접 쓰지 않는다)
    grounding: list[GroundingVerdict] = Field(default_factory=list)

    def verdict(self, kind: str, index: int) -> Verdict | None:
        for v in self.grounding:
            if v.kind == kind and v.index == index:
                return v.verdict
        return None


class ExtractionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output: ExtractionOutput


class GroundingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    verdicts: list[GroundingVerdict]


def structural_errors(output: ExtractionOutput, text: str) -> list[str]:
    """스키마는 맞지만 지침의 형식 규칙을 어긴 출력. 의미 판정은 하지 않는다."""
    errors = []
    names = {normalize_text(e.name) for e in output.entities}
    ids = set()

    def check_excerpt(label: str, excerpt: str) -> None:
        if excerpt not in text:
            errors.append(f"{label}: excerpt is not verbatim")

    for i, e in enumerate(output.events):
        ids.add(e.id)
        quantity = e.variable not in STATE_VARIABLES
        if quantity != (e.direction in QUANTITY_DIRECTIONS):
            errors.append(f"event {i}: direction {e.direction} does not fit {e.variable}")
        if normalize_text(e.entity) not in names:
            errors.append(f"event {i}: entity {e.entity!r} is not one of entities")
        if e.counterparty and normalize_text(e.counterparty) not in names:
            errors.append(f"event {i}: counterparty {e.counterparty!r} is not one of entities")
        check_excerpt(f"event {i}", e.excerpt)
    if len(ids) != len(output.events):
        errors.append("duplicate event id")
    for i, c in enumerate(output.causal_links):
        if c.cause not in ids or c.effect not in ids:
            errors.append(f"causal_link {i}: unknown event id")
        if c.evidence_level in GRAPH_EVIDENCE_LEVELS and not c.signal:
            errors.append(f"causal_link {i}: {c.evidence_level} needs a signal")
        check_excerpt(f"causal_link {i}", c.excerpt)
    for i, c in enumerate(output.claims):
        if c.predicate not in V3_PREDICATES:
            errors.append(f"claim {i}: predicate {c.predicate} is not used in v3")
        for role, name in (("subject", c.subject), ("object", c.object)):
            if normalize_text(name) not in names:
                errors.append(f"claim {i}: {role} {name!r} is not one of entities")
        check_excerpt(f"claim {i}", c.excerpt)
    return errors


def graph_view(output: ExtractionOutput) -> ClassificationOutput:
    """그래프에 넘길 v2 형식 출력. 근거 검증을 통과한 항목만 관계가 된다.

    - 관계: 판정 entailed, 실제(actual), 부정 아님.
    - 인과 연결: 판정 entailed, 근거 수준 mechanism·asserted, 원인·결과 사건의 개체가 서로 다를 때
      원인 개체 → 결과 개체 AFFECTS. 방향을 지어내지 않도록 polarity는 neutral로 둔다.
    - 주장별 태도는 쓰지 않으므로(D35) neutral.
    """
    claims: list[ClaimExtract] = []
    for i, c in enumerate(output.claims):
        if output.verdict("claim", i) != Verdict.ENTAILED:
            continue
        if c.modality != Modality.ACTUAL or c.negated or c.predicate not in V3_PREDICATES:
            continue
        claims.append(
            ClaimExtract(
                subject=c.subject,
                predicate=c.predicate,
                object=c.object,
                polarity=c.polarity,
                stance=Stance.NEUTRAL,
                evidence_status=_EVIDENCE[c.attribution],
                excerpt=c.excerpt,
            )
        )
    events = {e.id: e for e in output.events}
    for i, link in enumerate(output.causal_links):
        if output.verdict("causal_link", i) != Verdict.ENTAILED:
            continue
        if link.evidence_level not in GRAPH_EVIDENCE_LEVELS:
            continue
        cause, effect = events.get(link.cause), events.get(link.effect)
        if cause is None or effect is None or cause.negated or effect.negated:
            continue
        if normalize_text(cause.entity) == normalize_text(effect.entity):
            continue
        claims.append(
            ClaimExtract(
                subject=cause.entity,
                predicate=EdgeType.AFFECTS,
                object=effect.entity,
                polarity=Polarity.NEUTRAL,
                stance=Stance.NEUTRAL,
                evidence_status=_EVIDENCE[cause.attribution],
                excerpt=link.excerpt,
            )
        )
    return ClassificationOutput(
        relevance=output.relevance,
        is_noise=output.is_noise,
        language=output.language,
        entities=output.entities,
        stance=output.stance,
        # v2 상한을 넘으면 관계를 앞에서부터 쓴다 (관계 → 인과 연결 순)
        claims=claims[:GRAPH_MAX_CLAIMS],
        needs_review=output.needs_review,
        review_reason=output.review_reason,
    )

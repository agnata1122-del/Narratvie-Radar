"""DB, API, LLM 출력이 함께 쓰는 열거형. 값은 저장되므로 바꾸지 말고 추가만 한다."""

from enum import StrEnum


class SourceAccessStatus(StrEnum):
    NOT_AUTHORIZED = "not_authorized"  # 어댑터는 있지만 수집하지 않음
    TEST_MODE = "test_mode"  # 수동 import 데이터만
    LIVE = "live"
    PAUSED = "paused"  # 사람이 멈춤
    BLOCKED = "blocked"  # 차단 신호를 감지해 자동 중단. 사람이 확인 후 해제


class SourceKind(StrEnum):
    COMMUNITY = "community"
    MARKET = "market"
    OFFICIAL = "official"


class ContentAccessStatus(StrEnum):
    PERMITTED = "permitted"  # 이용 허락을 받은 원문
    UNVERIFIED = "unverified"  # 허락이 확인되지 않은 원문: 내부 분석만, 화면엔 발췌·링크만
    METADATA_ONLY = "metadata_only"  # 원문 없이 메타데이터만


class IngestMode(StrEnum):
    LIVE = "live"
    BACKFILL = "backfill"
    MANUAL_IMPORT = "manual_import"


class RunKind(StrEnum):
    SETUP = "setup"
    COLLECT = "collect"
    CLASSIFY = "classify"
    BUILD = "build"
    WIKI = "wiki"
    METRICS = "metrics"
    BACKFILL = "backfill"
    REPROCESS = "reprocess"


class RunMode(StrEnum):
    LIVE = "live"  # 당시 시스템이 실제로 알던 상태를 만든다
    RETROSPECTIVE = "retrospective"  # 사후 재구성. 포워드 성과와 섞지 않는다


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"


class ClassificationStatus(StrEnum):
    ACCEPTED = "accepted"
    REVIEW = "review"  # 불확실해서 사람 검토 대기 (PRD 6.3)
    REJECTED = "rejected"
    ERROR = "error"
    REFUSED = "refused"


class NodeType(StrEnum):
    COMPANY = "company"
    INDUSTRY = "industry"
    TECHNOLOGY = "technology"
    TOPIC = "topic"
    EVENT = "event"
    NARRATIVE = "narrative"  # PRD의 claim 노드 대신 (DECISIONS D5)


class NodeStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    DORMANT = "dormant"
    REJECTED = "rejected"
    MERGED = "merged"


class EdgeType(StrEnum):
    RELATED_TO = "RELATED_TO"
    PART_OF = "PART_OF"
    BELONGS_TO = "BELONGS_TO"
    SUPPLIES_TO = "SUPPLIES_TO"
    COMPETES_WITH = "COMPETES_WITH"
    AFFECTS = "AFFECTS"
    CLAIMED_CAUSE_OF = "CLAIMED_CAUSE_OF"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    CO_MENTIONED_WITH = "CO_MENTIONED_WITH"


class EdgeStatus(StrEnum):
    CANDIDATE = "candidate"  # 발견 후보: 점선
    CONFIRMED = "confirmed"  # 관측 확정 (독립 근거 기준 충족): 실선
    WEAKENED = "weakened"
    REJECTED = "rejected"


class EventType(StrEnum):
    NODE_CREATED = "NODE_CREATED"
    NODE_DORMANT = "NODE_DORMANT"
    NODE_REACTIVATED = "NODE_REACTIVATED"
    NODE_MERGED = "NODE_MERGED"
    NODE_REJECTED = "NODE_REJECTED"
    EDGE_CREATED = "EDGE_CREATED"
    EDGE_CONFIRMED = "EDGE_CONFIRMED"
    EDGE_WEAKENED = "EDGE_WEAKENED"
    EDGE_TYPE_CHANGED = "EDGE_TYPE_CHANGED"
    EDGE_REJECTED = "EDGE_REJECTED"
    NARRATIVE_CREATED = "NARRATIVE_CREATED"
    NARRATIVE_STATE_CHANGED = "NARRATIVE_STATE_CHANGED"
    WIKI_REVISED = "WIKI_REVISED"


class EventCause(StrEnum):
    OBSERVED_NEW = "observed_new"  # 새로 관측됨
    BACKFILL = "backfill"  # 과거 자료를 늦게 수집해 발견됨
    REPROCESS = "reprocess"  # 모델·프롬프트·스키마 변경으로 재분류됨
    SOURCE_ADDED = "source_added"
    USER_ACTION = "user_action"


class AliasOrigin(StrEnum):
    SEED = "seed"
    LLM = "llm"
    USER = "user"


class Stance(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class Polarity(StrEnum):
    GROWTH_DRIVER = "growth_driver"
    CONSTRAINT = "constraint"
    NEUTRAL = "neutral"


class EvidenceStatus(StrEnum):
    """주장이 어떤 성격으로 제시됐는가 (원문 기준)."""

    COMMUNITY_OPINION = "community_opinion"
    SPECULATION = "speculation"
    REPORTED_FACT = "reported_fact"  # 뉴스 등을 인용했다고 주장함 (확인 전)
    OFFICIAL_SOURCE = "official_source"


class VerificationStatus(StrEnum):
    """주장 내용이 확인됐는가. 확산 정도와는 별개다 (DECISIONS D6)."""

    UNVERIFIED = "unverified"
    SUPPORTED_BY_OFFICIAL = "supported_by_official"
    CONTRADICTED = "contradicted"


class NarrativeState(StrEnum):
    EMERGING = "emerging"
    SPREADING = "spreading"
    CONTESTED = "contested"
    REVERSED = "reversed"
    FADING = "fading"
    SPLIT = "split"


class NarrativeRole(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DETACHED = "detached"  # 다른 내러티브로 옮겨감


class ProfileNodeStatus(StrEnum):
    ADMITTED = "admitted"
    PENDING_REVIEW = "pending_review"
    EXCLUDED = "excluded"


class ViewerDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    HIDDEN = "hidden"


class TargetType(StrEnum):
    NODE = "node"
    EDGE = "edge"
    CLAIM = "claim"
    NARRATIVE = "narrative"
    CLASSIFICATION = "classification"
    WIKI = "wiki"


class SourceHealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"
    PAUSED = "paused"
    BLOCKED = "blocked"

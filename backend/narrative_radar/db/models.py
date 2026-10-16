"""DB 테이블 (PRD 16장 + DECISIONS D2–D10).

규칙
- 모든 시각은 UTCDateTime(시간대 필수)이다.
- `available_at`은 "시스템이 이 정보를 알 수 있게 된 시각"이다. 과거 상태 복원과 섀도 테스트는
  `available_at <= t`인 행만 쓴다.
- APPEND_ONLY_TABLES는 DB 트리거로 UPDATE/DELETE가 막혀 있다(마이그레이션 0001).
- nodes, edges, narratives, documents의 상태 컬럼은 현재 상태 캐시다. 과거 상태는 graph_events와
  이력 테이블로 복원한다.
"""

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from narrative_radar.db.types import UTCDateTime, str_enum
from narrative_radar.schemas.enums import (
    AliasOrigin,
    ClassificationStatus,
    ContentAccessStatus,
    EdgeStatus,
    EdgeType,
    EventCause,
    EventType,
    EvidenceStatus,
    IngestMode,
    NarrativeRole,
    NarrativeState,
    NodeStatus,
    NodeType,
    Polarity,
    ProfileNodeStatus,
    RunKind,
    RunMode,
    RunStatus,
    SourceAccessStatus,
    SourceHealthStatus,
    SourceKind,
    Stance,
    TargetType,
    VerificationStatus,
    ViewerDecision,
)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

ID = sa.String(40)

APPEND_ONLY_TABLES = (
    "classification_runs",
    "document_metric_snapshots",
    "edge_evidence",
    "graph_events",
    "narrative_claims",
    "node_metric_buckets",
    "profile_nodes",
    "wiki_revisions",
)


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: UTCDateTime(), dict[str, Any]: sa.JSON, list[Any]: sa.JSON}


def fk(target: str, **kw: Any) -> sa.ForeignKey:
    return sa.ForeignKey(target, **kw)


# --- 설정 ---------------------------------------------------------------------------------


class InterestProfile(Base):
    __tablename__ = "interest_profiles"
    __table_args__ = (
        sa.CheckConstraint("max_depth BETWEEN 0 AND 3", name="max_depth_range"),
        sa.CheckConstraint("max_new_nodes_per_day >= 0", name="budget_non_negative"),
        sa.CheckConstraint("minimum_independent_evidence >= 1", name="min_evidence_positive"),
    )

    profile_id: Mapped[str] = mapped_column(ID, primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    root_canonical_key: Mapped[str] = mapped_column(sa.String(200))
    max_depth: Mapped[int] = mapped_column(default=2)
    auto_expand: Mapped[bool] = mapped_column(default=True)
    max_new_nodes_per_day: Mapped[int] = mapped_column(default=15)
    minimum_independent_evidence: Mapped[int] = mapped_column(default=2)
    require_relevance: Mapped[bool] = mapped_column(default=True)
    allow_depth_overflow: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class SourceAdapter(Base):
    __tablename__ = "source_adapters"

    source_adapter_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    source: Mapped[str] = mapped_column(sa.String(64))
    kind: Mapped[SourceKind] = mapped_column(str_enum(SourceKind))
    display_name: Mapped[str] = mapped_column(sa.String(200))
    base_url: Mapped[str] = mapped_column(sa.String(500))
    access_status: Mapped[SourceAccessStatus] = mapped_column(str_enum(SourceAccessStatus))
    live_enabled: Mapped[bool] = mapped_column(default=False)
    status_reason: Mapped[str | None] = mapped_column(sa.Text)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime]


class PipelineRun(Base):
    """수집·분석 실행 하나. 모든 파생 데이터는 어떤 실행에서 나왔는지 가리킨다 (PRD 16.3-7)."""

    __tablename__ = "pipeline_runs"

    run_id: Mapped[str] = mapped_column(ID, primary_key=True)
    kind: Mapped[RunKind] = mapped_column(str_enum(RunKind))
    mode: Mapped[RunMode] = mapped_column(str_enum(RunMode))
    status: Mapped[RunStatus] = mapped_column(str_enum(RunStatus))
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    code_version: Mapped[str] = mapped_column(sa.String(64))
    model: Mapped[str | None] = mapped_column(sa.String(100))
    prompt_version: Mapped[str | None] = mapped_column(sa.String(64))
    schema_version: Mapped[str | None] = mapped_column(sa.String(64))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(sa.Text)


# --- 원천 데이터 ----------------------------------------------------------------------------


class DerivationGroup(Base):
    """복사·전재된 글 묶음. 확산은 문서 수로, 독립 근거는 그룹 수로 센다 (DECISIONS D6)."""

    __tablename__ = "derivation_groups"

    group_id: Mapped[str] = mapped_column(ID, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(sa.String(128), index=True)
    created_at: Mapped[datetime]
    available_at: Mapped[datetime]


class Document(Base):
    """원천 문서 메타데이터 (PRD 5.2). 댓글·조회 수는 document_metric_snapshots에 둔다 (D2)."""

    __tablename__ = "documents"
    # published_at은 출처 서버 시계라서 observed_at보다 늦을 수도 있다. 막지 않고 그대로 저장한다.
    __table_args__ = (sa.UniqueConstraint("source_adapter_id", "external_id"),)

    document_id: Mapped[str] = mapped_column(ID, primary_key=True)
    source_adapter_id: Mapped[str] = mapped_column(fk("source_adapters.source_adapter_id"))
    source: Mapped[str] = mapped_column(sa.String(64))
    source_type: Mapped[SourceKind] = mapped_column(str_enum(SourceKind))
    external_id: Mapped[str] = mapped_column(sa.String(128))
    # 답글·댓글도 각각 문서로 저장하고, 어디에 달린 글인지만 남긴다 (HN, Bluesky)
    parent_external_id: Mapped[str | None] = mapped_column(sa.String(128))
    thread_external_id: Mapped[str | None] = mapped_column(sa.String(128), index=True)
    source_url: Mapped[str] = mapped_column(sa.String(1000))
    title: Mapped[str] = mapped_column(sa.Text)
    author_hash: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    published_at: Mapped[datetime] = mapped_column(index=True)
    observed_at: Mapped[datetime]
    processed_at: Mapped[datetime | None]
    available_at: Mapped[datetime | None] = mapped_column(index=True)
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    content_access_status: Mapped[ContentAccessStatus] = mapped_column(
        str_enum(ContentAccessStatus)
    )
    ingest_mode: Mapped[IngestMode] = mapped_column(str_enum(IngestMode))
    collect_run_id: Mapped[str] = mapped_column(fk("pipeline_runs.run_id"))
    derivation_group_id: Mapped[str | None] = mapped_column(
        fk("derivation_groups.group_id"), index=True
    )
    deleted_observed_at: Mapped[datetime | None]


class RawDocument(Base):
    """원문 본문. 로컬 DB에만 존재하며 외부로 그대로 내보내지 않는다 (DATA_POLICY 9–10)."""

    __tablename__ = "raw_documents"

    document_id: Mapped[str] = mapped_column(fk("documents.document_id"), primary_key=True)
    body_text: Mapped[str] = mapped_column(sa.Text)
    fetched_at: Mapped[datetime]
    parser_version: Mapped[str] = mapped_column(sa.String(32))


class DocumentComment(Base):
    __tablename__ = "document_comments"
    __table_args__ = (sa.UniqueConstraint("document_id", "external_id"),)

    comment_id: Mapped[str] = mapped_column(ID, primary_key=True)
    document_id: Mapped[str] = mapped_column(fk("documents.document_id"), index=True)
    external_id: Mapped[str] = mapped_column(sa.String(128))
    parent_external_id: Mapped[str | None] = mapped_column(sa.String(128))
    author_hash: Mapped[str | None] = mapped_column(sa.String(64))
    body_text: Mapped[str] = mapped_column(sa.Text)
    published_at: Mapped[datetime | None]
    observed_at: Mapped[datetime]


class DocumentMetricSnapshot(Base):
    """그 시점에 보였던 댓글·조회·추천 수. 신호는 이 값만 쓴다 (D2)."""

    __tablename__ = "document_metric_snapshots"
    __table_args__ = (sa.UniqueConstraint("document_id", "observed_at"),)

    snapshot_id: Mapped[str] = mapped_column(ID, primary_key=True)
    document_id: Mapped[str] = mapped_column(fk("documents.document_id"), index=True)
    observed_at: Mapped[datetime]
    comment_count: Mapped[int | None]
    view_count: Mapped[int | None]
    upvote_count: Mapped[int | None]
    downvote_count: Mapped[int | None]
    share_count: Mapped[int | None]  # 리포스트·인용 등 확산 지표 (Bluesky)
    collect_run_id: Mapped[str] = mapped_column(fk("pipeline_runs.run_id"))


class SourceHealth(Base):
    """수집 상태 시계열. 공백 구간의 관심도 하락을 신호로 오인하지 않기 위해 쓴다 (D10)."""

    __tablename__ = "source_health"
    __table_args__ = (sa.CheckConstraint("window_end > window_start", name="window_order"),)

    health_id: Mapped[str] = mapped_column(ID, primary_key=True)
    source_adapter_id: Mapped[str] = mapped_column(
        fk("source_adapters.source_adapter_id"), index=True
    )
    window_start: Mapped[datetime]
    window_end: Mapped[datetime]
    status: Mapped[SourceHealthStatus] = mapped_column(str_enum(SourceHealthStatus))
    requests: Mapped[int] = mapped_column(default=0)
    successes: Mapped[int] = mapped_column(default=0)
    failures: Mapped[int] = mapped_column(default=0)
    documents_listed: Mapped[int] = mapped_column(default=0)
    documents_fetched: Mapped[int] = mapped_column(default=0)
    note: Mapped[str | None] = mapped_column(sa.Text)
    recorded_at: Mapped[datetime]


# --- 분류 ---------------------------------------------------------------------------------


class ClassificationRun(Base):
    """LLM 분류 결과 원본. 반영 전 변경안이며 수정하지 않는다."""

    __tablename__ = "classification_runs"

    classification_id: Mapped[str] = mapped_column(ID, primary_key=True)
    document_id: Mapped[str] = mapped_column(fk("documents.document_id"), index=True)
    # 어느 내용 버전을 분류했는지. 글이 수정되면 다시 분류 대상이 된다.
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    run_id: Mapped[str] = mapped_column(fk("pipeline_runs.run_id"))
    model: Mapped[str] = mapped_column(sa.String(100))
    prompt_version: Mapped[str] = mapped_column(sa.String(64))
    schema_version: Mapped[str] = mapped_column(sa.String(64))
    status: Mapped[ClassificationStatus] = mapped_column(str_enum(ClassificationStatus))
    requested_at: Mapped[datetime]
    completed_at: Mapped[datetime]
    output: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON)
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(sa.Text)


# --- 지식 그래프 ----------------------------------------------------------------------------


class Node(Base):
    __tablename__ = "nodes"

    node_id: Mapped[str] = mapped_column(ID, primary_key=True)
    canonical_key: Mapped[str] = mapped_column(sa.String(200), unique=True)
    node_type: Mapped[NodeType] = mapped_column(str_enum(NodeType))
    label: Mapped[str] = mapped_column(sa.String(300))
    status: Mapped[NodeStatus] = mapped_column(str_enum(NodeStatus))
    merged_into_node_id: Mapped[str | None] = mapped_column(fk("nodes.node_id"))
    created_at: Mapped[datetime]
    available_at: Mapped[datetime] = mapped_column(index=True)
    created_run_id: Mapped[str] = mapped_column(fk("pipeline_runs.run_id"))


class NodeAlias(Base):
    __tablename__ = "node_aliases"
    __table_args__ = (sa.UniqueConstraint("node_id", "alias_normalized"),)

    alias_id: Mapped[str] = mapped_column(ID, primary_key=True)
    node_id: Mapped[str] = mapped_column(fk("nodes.node_id"), index=True)
    alias: Mapped[str] = mapped_column(sa.String(300))
    alias_normalized: Mapped[str] = mapped_column(sa.String(300), index=True)
    lang: Mapped[str | None] = mapped_column(sa.String(8))
    origin: Mapped[AliasOrigin] = mapped_column(str_enum(AliasOrigin))
    created_at: Mapped[datetime]
    available_at: Mapped[datetime]


class Narrative(Base):
    """같은 명제를 말하는 주장 묶음 (DECISIONS D5). 그래프에서는 narrative 노드로 나타난다."""

    __tablename__ = "narratives"

    narrative_id: Mapped[str] = mapped_column(ID, primary_key=True)
    node_id: Mapped[str] = mapped_column(fk("nodes.node_id"), unique=True)
    proposition: Mapped[str] = mapped_column(sa.Text)
    state: Mapped[NarrativeState] = mapped_column(str_enum(NarrativeState))
    created_at: Mapped[datetime]
    available_at: Mapped[datetime]


class Claim(Base):
    """문서 하나에서 추출된 주장. 내용의 사실 여부는 verification_status로 따로 둔다 (D6)."""

    __tablename__ = "claims"

    claim_id: Mapped[str] = mapped_column(ID, primary_key=True)
    document_id: Mapped[str] = mapped_column(fk("documents.document_id"), index=True)
    classification_id: Mapped[str] = mapped_column(fk("classification_runs.classification_id"))
    subject_text: Mapped[str] = mapped_column(sa.String(300))
    subject_node_id: Mapped[str | None] = mapped_column(fk("nodes.node_id"), index=True)
    predicate: Mapped[EdgeType] = mapped_column(str_enum(EdgeType))
    object_text: Mapped[str] = mapped_column(sa.String(300))
    object_node_id: Mapped[str | None] = mapped_column(fk("nodes.node_id"), index=True)
    polarity: Mapped[Polarity] = mapped_column(str_enum(Polarity))
    stance: Mapped[Stance] = mapped_column(str_enum(Stance))
    evidence_status: Mapped[EvidenceStatus] = mapped_column(str_enum(EvidenceStatus))
    verification_status: Mapped[VerificationStatus] = mapped_column(
        str_enum(VerificationStatus), default=VerificationStatus.UNVERIFIED
    )
    excerpt: Mapped[str | None] = mapped_column(sa.String(500))
    created_at: Mapped[datetime]
    available_at: Mapped[datetime]


class NarrativeClaim(Base):
    """주장의 내러티브 배정 이력. 시점 t의 배정은 available_at <= t인 마지막 행이다."""

    __tablename__ = "narrative_claims"

    assignment_id: Mapped[str] = mapped_column(ID, primary_key=True)
    narrative_id: Mapped[str] = mapped_column(fk("narratives.narrative_id"), index=True)
    claim_id: Mapped[str] = mapped_column(fk("claims.claim_id"), index=True)
    role: Mapped[NarrativeRole] = mapped_column(str_enum(NarrativeRole))
    available_at: Mapped[datetime]
    run_id: Mapped[str] = mapped_column(fk("pipeline_runs.run_id"))


class Edge(Base):
    __tablename__ = "edges"
    __table_args__ = (
        sa.UniqueConstraint("source_node_id", "target_node_id", "relation_type"),
        sa.CheckConstraint("source_node_id <> target_node_id", name="no_self_loop"),
    )

    edge_id: Mapped[str] = mapped_column(ID, primary_key=True)
    source_node_id: Mapped[str] = mapped_column(fk("nodes.node_id"), index=True)
    target_node_id: Mapped[str] = mapped_column(fk("nodes.node_id"), index=True)
    relation_type: Mapped[EdgeType] = mapped_column(str_enum(EdgeType))
    status: Mapped[EdgeStatus] = mapped_column(str_enum(EdgeStatus))
    created_at: Mapped[datetime]
    available_at: Mapped[datetime]
    created_run_id: Mapped[str] = mapped_column(fk("pipeline_runs.run_id"))


class EdgeEvidence(Base):
    """관계의 근거. 문서 하나는 관계 하나에 근거를 한 번만 더한다."""

    __tablename__ = "edge_evidence"
    __table_args__ = (sa.UniqueConstraint("edge_id", "document_id"),)

    evidence_id: Mapped[str] = mapped_column(ID, primary_key=True)
    edge_id: Mapped[str] = mapped_column(fk("edges.edge_id"), index=True)
    document_id: Mapped[str] = mapped_column(fk("documents.document_id"), index=True)
    claim_id: Mapped[str | None] = mapped_column(fk("claims.claim_id"))
    derivation_group_id: Mapped[str | None] = mapped_column(fk("derivation_groups.group_id"))
    author_hash: Mapped[str | None] = mapped_column(sa.String(64))
    available_at: Mapped[datetime] = mapped_column(index=True)
    run_id: Mapped[str] = mapped_column(fk("pipeline_runs.run_id"))


class GraphEvent(Base):
    """그래프 변화 이력 (PRD 10.2). 원인(cause)으로 실제 변화와 분석 변경을 구분한다 (D7)."""

    __tablename__ = "graph_events"
    __table_args__ = (
        sa.CheckConstraint(
            "node_id IS NOT NULL OR edge_id IS NOT NULL OR narrative_id IS NOT NULL",
            name="has_target",
        ),
        sa.CheckConstraint("available_at >= recorded_at", name="available_after_recorded"),
    )

    event_id: Mapped[str] = mapped_column(ID, primary_key=True)
    event_type: Mapped[EventType] = mapped_column(str_enum(EventType))
    cause: Mapped[EventCause] = mapped_column(str_enum(EventCause))
    node_id: Mapped[str | None] = mapped_column(fk("nodes.node_id"), index=True)
    edge_id: Mapped[str | None] = mapped_column(fk("edges.edge_id"), index=True)
    narrative_id: Mapped[str | None] = mapped_column(fk("narratives.narrative_id"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    evidence_document_ids: Mapped[list[Any]] = mapped_column(default=list)
    event_time: Mapped[datetime | None]
    recorded_at: Mapped[datetime]
    available_at: Mapped[datetime] = mapped_column(index=True)
    run_id: Mapped[str] = mapped_column(fk("pipeline_runs.run_id"))


class WikiRevision(Base):
    """위키 버전. 이전 버전은 지우지 않으며, 재생 시 그 시점의 버전을 쓴다 (PRD 9.4)."""

    __tablename__ = "wiki_revisions"
    __table_args__ = (sa.UniqueConstraint("node_id", "version"),)

    revision_id: Mapped[str] = mapped_column(ID, primary_key=True)
    node_id: Mapped[str] = mapped_column(fk("nodes.node_id"), index=True)
    version: Mapped[int]
    sections: Mapped[list[Any]] = mapped_column(default=list)
    section_fingerprints: Mapped[dict[str, Any]] = mapped_column(default=dict)
    source_document_ids: Mapped[list[Any]] = mapped_column(default=list)
    model: Mapped[str | None] = mapped_column(sa.String(100))
    prompt_version: Mapped[str | None] = mapped_column(sa.String(64))
    schema_version: Mapped[str] = mapped_column(sa.String(64))
    updated_at: Mapped[datetime]
    available_at: Mapped[datetime]
    run_id: Mapped[str] = mapped_column(fk("pipeline_runs.run_id"))


class NodeMetricBucket(Base):
    """노드 언급 지표. 늦게 들어온 자료가 과거 버킷을 바꾸지 않도록, 다시 계산하면 새 행을
    추가한다. 시점 t의 값은 같은 버킷에서 available_at <= t인 마지막 행이다."""

    __tablename__ = "node_metric_buckets"
    __table_args__ = (
        sa.UniqueConstraint(
            "node_id", "source_adapter_id", "bucket_start", "bucket_seconds", "available_at"
        ),
        sa.CheckConstraint("bucket_seconds > 0", name="bucket_positive"),
    )

    bucket_row_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(fk("nodes.node_id"), index=True)
    source_adapter_id: Mapped[str] = mapped_column(fk("source_adapters.source_adapter_id"))
    bucket_start: Mapped[datetime]
    bucket_seconds: Mapped[int]
    mention_count: Mapped[int]
    independent_count: Mapped[int]
    source_total_documents: Mapped[int]
    available_at: Mapped[datetime]
    run_id: Mapped[str] = mapped_column(fk("pipeline_runs.run_id"))


# --- 개인화 ---------------------------------------------------------------------------------


class ProfileNode(Base):
    """관심사별 자동 확장 결정 이력 (PRD 8.3). 일일 신규 노드 예산 계산에도 쓴다."""

    __tablename__ = "profile_nodes"

    decision_id: Mapped[str] = mapped_column(ID, primary_key=True)
    profile_id: Mapped[str] = mapped_column(fk("interest_profiles.profile_id"), index=True)
    node_id: Mapped[str] = mapped_column(fk("nodes.node_id"), index=True)
    status: Mapped[ProfileNodeStatus] = mapped_column(str_enum(ProfileNodeStatus))
    depth: Mapped[int | None]
    reason: Mapped[str | None] = mapped_column(sa.Text)
    available_at: Mapped[datetime]
    run_id: Mapped[str] = mapped_column(fk("pipeline_runs.run_id"))


class Viewer(Base):
    """익명 방문자. 개인 오버레이·저장 뷰·피드백을 묶는 용도로만 쓴다."""

    __tablename__ = "viewers"

    viewer_id: Mapped[str] = mapped_column(ID, primary_key=True)
    created_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]


class ViewerOverlay(Base):
    """방문자별 승인·거절·숨김. 공통 그래프는 바꾸지 않는다 (PRD 8.4)."""

    __tablename__ = "viewer_overlays"

    viewer_id: Mapped[str] = mapped_column(fk("viewers.viewer_id"), primary_key=True)
    profile_id: Mapped[str] = mapped_column(fk("interest_profiles.profile_id"), primary_key=True)
    target_type: Mapped[TargetType] = mapped_column(str_enum(TargetType), primary_key=True)
    target_id: Mapped[str] = mapped_column(ID, primary_key=True)
    decision: Mapped[ViewerDecision] = mapped_column(str_enum(ViewerDecision))
    created_at: Mapped[datetime]


class SavedView(Base):
    __tablename__ = "saved_views"

    view_id: Mapped[str] = mapped_column(ID, primary_key=True)
    viewer_id: Mapped[str | None] = mapped_column(fk("viewers.viewer_id"), index=True)
    profile_id: Mapped[str] = mapped_column(fk("interest_profiles.profile_id"))
    name: Mapped[str] = mapped_column(sa.String(200))
    filters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ClassificationFeedback(Base):
    """테스터 피드백. 모델·프롬프트·스키마 버전과 함께 저장한다 (PRD 20.5)."""

    __tablename__ = "classification_feedback"

    feedback_id: Mapped[str] = mapped_column(ID, primary_key=True)
    viewer_id: Mapped[str | None] = mapped_column(fk("viewers.viewer_id"))
    target_type: Mapped[TargetType] = mapped_column(str_enum(TargetType))
    target_id: Mapped[str] = mapped_column(ID)
    rating: Mapped[int | None]
    label: Mapped[str | None] = mapped_column(sa.String(100))
    comment: Mapped[str | None] = mapped_column(sa.Text)
    model: Mapped[str | None] = mapped_column(sa.String(100))
    prompt_version: Mapped[str | None] = mapped_column(sa.String(64))
    schema_version: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[datetime]

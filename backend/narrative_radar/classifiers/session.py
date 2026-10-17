"""세션 분류 흐름 (DECISIONS D16).

1. export_batch: 분류할 글과 온톨로지를 파일로 내보낸다.
2. Claude Code 세션이 guidelines/classification_v2.md(+ 도메인 팩 보충)에 따라
   ClassificationRecord JSONL을 쓴다.
3. ingest_records: 스키마와 구조 규칙을 검증해 classification_runs에 저장한다.
   그래프 반영(M5)은 이 기록을 다시 검증한 뒤에 한다.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.orm import Session, aliased

from narrative_radar.classifiers import rule_based
from narrative_radar.classifiers.ontology import Ontology, load_ontology, valid_key
from narrative_radar.core.clock import Clock
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import (
    ClassificationRun,
    Document,
    InterestProfile,
    Node,
    RawDocument,
)
from narrative_radar.domains import DomainPack
from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas.classification import (
    SCHEMA_VERSION,
    ClassificationOutput,
    ClassificationRecord,
)
from narrative_radar.schemas.enums import (
    ClassificationStatus,
    ContentAccessStatus,
    NodeType,
    ProfileNodeStatus,
)

# v2: 분야와 무관한 공통 지침 (DECISIONS D22). 실제 기록에는 도메인 팩 버전을 붙인다.
PROMPT_VERSION = "classification.v2"
GUIDELINES = Path(__file__).parent / "guidelines" / "classification_v2.md"


def prompt_version_for(pack: DomainPack) -> str:
    """공통 지침 + 팩 보충 지침의 조합. 둘 중 하나가 바뀌면 다시 분류할 대상이 된다."""
    return f"{PROMPT_VERSION}+{pack.version}"


def guidelines_for(pack: DomainPack) -> list[Path]:
    return [GUIDELINES, *([pack.guideline] if pack.guideline else [])]


MAX_TEXT_CHARS = 4000
MAX_PARENT_CHARS = 500
MAX_KNOWN_NODES = 20  # 글마다 붙이는 기존 노드 단서
# 온톨로지가 이보다 크면 관심사 트리의 노드와 이번 글들에 나온 노드만 넘긴다 (광역 수집으로 커진다)
MAX_CONTEXT_NODES = 400


def pending_documents(
    session: Session, limit: int, prompt_version: str = PROMPT_VERSION
) -> list[Document]:
    """이 지침·스키마 버전으로 현재 내용을 아직 분류하지 않은 글. 오류였던 분류는 다시 한다."""
    done = (
        sa.select(ClassificationRun.classification_id)
        .where(
            ClassificationRun.document_id == Document.document_id,
            ClassificationRun.content_hash == Document.content_hash,
            ClassificationRun.prompt_version == prompt_version,
            ClassificationRun.schema_version == SCHEMA_VERSION,
            ClassificationRun.status != ClassificationStatus.ERROR,
        )
        .exists()
    )
    return list(
        session.scalars(
            sa.select(Document)
            .where(
                Document.deleted_observed_at.is_(None),
                Document.content_access_status != ContentAccessStatus.METADATA_ONLY,
                ~done,
            )
            .order_by(Document.published_at)
            .limit(limit)
        )
    )


def _text(session: Session, doc: Document) -> str:
    raw = session.get(RawDocument, doc.document_id)
    body = raw.body_text if raw else ""
    return "\n".join(part for part in (doc.title, body) if part)


def _tree_keys(session: Session) -> set[str]:
    """관심사 트리에 들어 있는(포함 결정이 난) 노드의 키."""
    from narrative_radar.discovery.expansion import latest_decisions

    node_ids: set[str] = set()
    for profile_id in session.scalars(sa.select(InterestProfile.profile_id)):
        node_ids |= {
            node_id
            for node_id, status in latest_decisions(session, profile_id).items()
            if status == ProfileNodeStatus.ADMITTED
        }
    return set(session.scalars(sa.select(Node.canonical_key).where(Node.node_id.in_(node_ids))))


def export_batch(
    session: Session, clock: Clock, limit: int, out_dir: Path, pack: DomainPack
) -> tuple[Path, Path, int]:
    """batch.jsonl(글)과 context.json(온톨로지·규칙·지침)을 쓴다. 글 수를 돌려준다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    docs = pending_documents(session, limit, prompt_version_for(pack))
    ontology = load_ontology(session)
    mentioned: set[str] = set()
    parent = aliased(Document)
    batch_path = out_dir / "batch.jsonl"
    with batch_path.open("w", encoding="utf-8") as f:
        for doc in docs:
            parent_text = None
            if doc.parent_external_id:
                p = session.scalar(
                    sa.select(parent).where(
                        parent.source_adapter_id == doc.source_adapter_id,
                        parent.external_id == doc.parent_external_id,
                        parent.deleted_observed_at.is_(None),
                    )
                )
                if p is not None:
                    parent_text = _text(session, p)[:MAX_PARENT_CHARS]
            text = _text(session, doc)[:MAX_TEXT_CHARS]
            known = ontology.matching(f"{text}\n{parent_text or ''}", MAX_KNOWN_NODES)
            mentioned |= {n.canonical_key for n in known}
            line = {
                "document_id": doc.document_id,
                "content_hash": doc.content_hash,
                "source": doc.source,
                "published_at": doc.published_at.isoformat(),
                # 본문 없이 제목만 있는 글 (발견 공급자가 준 헤드라인, D25)
                "headline_only": session.get(RawDocument, doc.document_id) is None,
                "text": text,
                "parent_text": parent_text,
                # 이 글에 이름·별칭이 나온 기존 노드. 같은 대상이면 이 키를 쓴다
                "known_nodes": [
                    {"canonical_key": n.canonical_key, "label": n.label} for n in known
                ],
            }
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    truncated = len(ontology.nodes) > MAX_CONTEXT_NODES
    if truncated:
        keep = sorted(_tree_keys(session) | mentioned)[:MAX_CONTEXT_NODES]
        ontology = ontology.only(keep)
    context_path = out_dir / "context.json"
    context = {
        "exported_at": clock.now().isoformat(),
        "prompt_version": prompt_version_for(pack),
        "schema_version": SCHEMA_VERSION,
        "domain": {"id": pack.id, "name": pack.name, "version": pack.version},
        "interests": _interests(session, pack),
        "guidelines": [str(g) for g in guidelines_for(pack)],
        "ontology": ontology.to_dict(pack),
        # 잘렸으면 여기 없는 노드도 있다. 새 키를 만들기 전에 known_nodes와 별칭을 먼저 본다
        "ontology_truncated": truncated,
    }
    context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    return batch_path, context_path, len(docs)


def _interests(session: Session, pack: DomainPack) -> list[dict[str, str]]:
    """이 팩을 쓰는 관심사(루트). 분류할 때 relevance·stance의 기준이 된다."""
    rows = session.execute(
        sa.select(InterestProfile.name, InterestProfile.root_canonical_key, Node.label)
        .outerjoin(Node, Node.canonical_key == InterestProfile.root_canonical_key)
        .where(InterestProfile.domain == pack.id)
        .order_by(InterestProfile.created_at)
    ).all()
    return [{"name": n, "root_key": k, "root_label": label or k} for n, k, label in rows]


def structural_errors(output: ClassificationOutput) -> list[str]:
    """스키마는 맞지만 그래프에 넣을 수 없는 출력."""
    errors = []
    names = {normalize_text(e.name) for e in output.entities}
    for e in output.entities:
        if e.canonical_key is not None and not valid_key(e.type, e.canonical_key):
            errors.append(f"invalid canonical_key for {e.type.value}: {e.canonical_key!r}")
    for i, c in enumerate(output.claims):
        if normalize_text(c.subject) not in names:
            errors.append(f"claim {i}: subject {c.subject!r} is not one of entities")
        if normalize_text(c.object) not in names:
            errors.append(f"claim {i}: object {c.object!r} is not one of entities")
        if c.narrative_key and c.narrative_proposition:
            errors.append(f"claim {i}: give narrative_key or narrative_proposition, not both")
        if (c.narrative_key or c.narrative_proposition) and c.narrative_role is None:
            errors.append(f"claim {i}: narrative_role is required with a narrative")
        if c.narrative_key and not valid_key(NodeType.NARRATIVE, c.narrative_key):
            errors.append(f"claim {i}: invalid narrative_key {c.narrative_key!r}")
    return errors


@dataclass
class IngestReport:
    accepted: int = 0
    review: int = 0
    errors: list[str] = field(default_factory=list)
    stale: int = 0
    duplicates: int = 0


def ingest_records(
    session: Session,
    clock: Clock,
    lines: Iterable[str],
    model: str,
    run_id: str,
    prompt_version: str = PROMPT_VERSION,
    requested_at: datetime | None = None,
) -> IngestReport:
    report = IngestReport()
    now = clock.now()
    requested_at = requested_at or now
    seen: set[str] = set()
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = ClassificationRecord.model_validate_json(line)
        except ValidationError as e:
            doc_id = _peek_document_id(line)
            report.errors.append(f"line {line_no}: {e.error_count()} schema errors")
            if doc_id and session.get(Document, doc_id) is not None:
                _store(
                    session,
                    doc_id,
                    _peek(line, "content_hash") or "",
                    model,
                    run_id,
                    prompt_version,
                    requested_at,
                    now,
                    ClassificationStatus.ERROR,
                    None,
                    f"schema: {e.errors(include_url=False)[:5]}",
                )
            continue

        doc = session.get(Document, record.document_id)
        if doc is None:
            report.errors.append(f"line {line_no}: unknown document {record.document_id}")
            continue
        if doc.deleted_observed_at is not None or doc.content_hash != record.content_hash:
            report.stale += 1  # 그사이 지워졌거나 수정됨: 다음 배치에서 다시 분류한다
            continue
        if record.document_id in seen:
            report.duplicates += 1
            continue
        seen.add(record.document_id)

        problems = structural_errors(record.output)
        if problems:
            report.errors.append(f"line {line_no}: " + "; ".join(problems))
            status, error = ClassificationStatus.ERROR, "; ".join(problems)
        elif record.output.needs_review:
            report.review += 1
            status, error = ClassificationStatus.REVIEW, None
        else:
            report.accepted += 1
            status, error = ClassificationStatus.ACCEPTED, None
        _store(
            session,
            doc.document_id,
            record.content_hash,
            model,
            run_id,
            prompt_version,
            requested_at,
            now,
            status,
            record.output.model_dump(mode="json"),
            error,
        )
    return report


def run_baseline(session: Session, clock: Clock, run_id: str, root_key: str, limit: int) -> int:
    """규칙 기반 분류기로 대기 중인 글을 분류해 바로 저장한다."""
    ontology: Ontology = load_ontology(session)
    docs = pending_documents(session, limit, prompt_version=rule_based.MODEL_LABEL)
    now = clock.now()
    for doc in docs:
        output = rule_based.classify(_text(session, doc), ontology, root_key)
        _store(
            session,
            doc.document_id,
            doc.content_hash,
            rule_based.MODEL_LABEL,
            run_id,
            rule_based.MODEL_LABEL,
            now,
            now,
            ClassificationStatus.ACCEPTED,
            output.model_dump(mode="json"),
            None,
        )
    return len(docs)


def _store(
    session: Session,
    document_id: str,
    content_hash: str,
    model: str,
    run_id: str,
    prompt_version: str,
    requested_at: datetime,
    completed_at: datetime,
    status: ClassificationStatus,
    output: dict[str, object] | None,
    error: str | None,
) -> None:
    session.add(
        ClassificationRun(
            classification_id=new_id("cls", completed_at),
            document_id=document_id,
            content_hash=content_hash,
            run_id=run_id,
            model=model,
            prompt_version=prompt_version,
            schema_version=SCHEMA_VERSION,
            status=status,
            requested_at=requested_at,
            completed_at=completed_at,
            output=output,
            error=error,
        )
    )
    session.flush()


def _peek(line: str, key: str) -> str | None:
    try:
        value = json.loads(line).get(key)
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def _peek_document_id(line: str) -> str | None:
    return _peek(line, "document_id")

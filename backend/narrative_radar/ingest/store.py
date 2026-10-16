"""수집 결과를 DB에 저장한다.

- 같은 글을 다시 받아도 문서는 하나다 (source_adapter_id, external_id).
- 댓글·조회 수는 받을 때마다 관측 시각과 함께 스냅샷으로 쌓는다 (DECISIONS D2).
- 출처에서 지워진 글은 원문을 지우고 삭제 시각만 남긴다 (DATA_POLICY 12).
  한 번 지워진 글은 다시 받아도 되살리지 않는다.
"""

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.core.clock import ensure_utc
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import (
    Claim,
    Document,
    DocumentComment,
    DocumentMetricSnapshot,
    RawDocument,
    SourceAdapter,
)
from narrative_radar.normalization.text import content_hash
from narrative_radar.schemas.document import DocumentIn, MetricsIn
from narrative_radar.schemas.enums import ContentAccessStatus

DELETED_TITLE = ""


@dataclass(frozen=True)
class StoreResult:
    document_id: str
    created: bool
    content_changed: bool
    snapshot_added: bool
    ignored_deleted: bool = False


class DocumentStore:
    def __init__(self, session: Session, collect_run_id: str, parser_version: str) -> None:
        self.session = session
        self.collect_run_id = collect_run_id
        self.parser_version = parser_version
        self._adapters: dict[str, SourceAdapter] = {}

    def save(self, doc: DocumentIn) -> StoreResult:
        adapter = self._adapter(doc.source_adapter_id)
        existing = self._find(doc.source_adapter_id, doc.external_id)
        observed_at = ensure_utc(doc.observed_at)
        digest = content_hash(doc.title, doc.body_text)
        keep_text = doc.content_access_status != ContentAccessStatus.METADATA_ONLY

        if existing is not None and existing.deleted_observed_at is not None:
            return StoreResult(existing.document_id, False, False, False, ignored_deleted=True)

        if existing is None:
            document = Document(
                document_id=new_id("doc", observed_at),
                source_adapter_id=adapter.source_adapter_id,
                source=adapter.source,
                source_type=adapter.kind,
                external_id=doc.external_id,
                parent_external_id=doc.parent_external_id,
                thread_external_id=doc.thread_external_id,
                source_url=doc.source_url,
                title=doc.title if keep_text else DELETED_TITLE,
                author_hash=doc.author_hash,
                published_at=doc.published_at,
                observed_at=observed_at,
                content_hash=digest,
                content_access_status=doc.content_access_status,
                ingest_mode=doc.ingest_mode,
                collect_run_id=self.collect_run_id,
            )
            self.session.add(document)
            self.session.flush()
            if keep_text and doc.body_text is not None:
                self.session.add(
                    RawDocument(
                        document_id=document.document_id,
                        body_text=doc.body_text,
                        fetched_at=observed_at,
                        parser_version=self.parser_version,
                    )
                )
            created, changed = True, False
        else:
            document = existing
            created = False
            changed = digest != document.content_hash
            if changed and keep_text:
                # 수정된 글: 최신 내용으로 바꾸고 다시 분석하게 한다. 이전 분석은 이력으로 남는다.
                document.title = doc.title
                document.content_hash = digest
                document.processed_at = None
                raw = self.session.get(RawDocument, document.document_id)
                if doc.body_text is None:
                    if raw is not None:
                        self.session.delete(raw)
                elif raw is None:
                    self.session.add(
                        RawDocument(
                            document_id=document.document_id,
                            body_text=doc.body_text,
                            fetched_at=observed_at,
                            parser_version=self.parser_version,
                        )
                    )
                else:
                    raw.body_text = doc.body_text
                    raw.fetched_at = observed_at
                    raw.parser_version = self.parser_version

        if keep_text:
            self._add_comments(document.document_id, doc, observed_at)
        snapshot_added = self._add_snapshot(document.document_id, observed_at, doc.metrics)
        return StoreResult(document.document_id, created, changed, snapshot_added)

    def add_metrics(
        self, source_adapter_id: str, external_id: str, observed_at: datetime, metrics: MetricsIn
    ) -> bool:
        """스냅샷 재방문(+10분, +1시간 …)에서 얻은 지표만 추가한다."""
        document = self._find(source_adapter_id, external_id)
        if document is None or document.deleted_observed_at is not None:
            return False
        return self._add_snapshot(document.document_id, ensure_utc(observed_at), metrics)

    def mark_deleted(self, source_adapter_id: str, external_id: str, observed_at: datetime) -> bool:
        """출처에서 지워진 글의 원문을 지운다. 저장한 적 없는 글이면 False."""
        document = self._find(source_adapter_id, external_id)
        if document is None:
            return False
        if document.deleted_observed_at is not None:
            return True
        document.deleted_observed_at = ensure_utc(observed_at)
        document.title = DELETED_TITLE
        raw = self.session.get(RawDocument, document.document_id)
        if raw is not None:
            self.session.delete(raw)
        self.session.execute(
            sa.delete(DocumentComment).where(DocumentComment.document_id == document.document_id)
        )
        self.session.execute(
            sa.update(Claim).where(Claim.document_id == document.document_id).values(excerpt=None)
        )
        return True

    def mark_author_deleted(
        self, source_adapter_id: str, author_hash: str, observed_at: datetime
    ) -> int:
        """계정이 삭제·정지되면 그 계정의 글을 모두 지운다 (Bluesky 개발자 가이드라인)."""
        ids = self.session.scalars(
            sa.select(Document.external_id).where(
                Document.source_adapter_id == source_adapter_id,
                Document.author_hash == author_hash,
                Document.deleted_observed_at.is_(None),
            )
        ).all()
        for external_id in ids:
            self.mark_deleted(source_adapter_id, external_id, observed_at)
        return len(ids)

    def _adapter(self, source_adapter_id: str) -> SourceAdapter:
        adapter = self._adapters.get(source_adapter_id)
        if adapter is None:
            adapter = self.session.get(SourceAdapter, source_adapter_id)
            if adapter is None:
                raise KeyError(f"unknown source adapter: {source_adapter_id}")
            self._adapters[source_adapter_id] = adapter
        return adapter

    def _find(self, source_adapter_id: str, external_id: str) -> Document | None:
        return self.session.scalar(
            sa.select(Document).where(
                Document.source_adapter_id == source_adapter_id,
                Document.external_id == external_id,
            )
        )

    def _add_comments(self, document_id: str, doc: DocumentIn, observed_at: datetime) -> None:
        if not doc.comments:
            return
        known = set(
            self.session.scalars(
                sa.select(DocumentComment.external_id).where(
                    DocumentComment.document_id == document_id
                )
            )
        )
        for c in doc.comments:
            if c.external_id in known:
                continue
            known.add(c.external_id)
            self.session.add(
                DocumentComment(
                    comment_id=new_id("cmt", observed_at),
                    document_id=document_id,
                    external_id=c.external_id,
                    parent_external_id=c.parent_external_id,
                    author_hash=c.author_hash,
                    body_text=c.body_text,
                    published_at=c.published_at,
                    observed_at=observed_at,
                )
            )

    def _add_snapshot(
        self, document_id: str, observed_at: datetime, metrics: MetricsIn | None
    ) -> bool:
        if metrics is None:
            return False
        exists = self.session.scalar(
            sa.select(DocumentMetricSnapshot.snapshot_id).where(
                DocumentMetricSnapshot.document_id == document_id,
                DocumentMetricSnapshot.observed_at == observed_at,
            )
        )
        if exists:
            return False
        self.session.add(
            DocumentMetricSnapshot(
                snapshot_id=new_id("met", observed_at),
                document_id=document_id,
                observed_at=observed_at,
                comment_count=metrics.comment_count,
                view_count=metrics.view_count,
                upvote_count=metrics.upvote_count,
                downvote_count=metrics.downvote_count,
                collect_run_id=self.collect_run_id,
            )
        )
        return True

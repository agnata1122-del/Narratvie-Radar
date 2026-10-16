"""수집 현황 요약. M2(수집 가능성 확인)와 포워드 수집 점검에 쓴다."""

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.db.models import Document, DocumentMetricSnapshot, SourceAdapter, SourceHealth
from narrative_radar.schemas.enums import IngestMode


@dataclass
class SourceReport:
    source_adapter_id: str
    access_status: str
    documents_in_window: int
    live: int
    backfill: int
    deleted: int
    snapshots: int
    median_delay_seconds: float | None
    per_hour: dict[str, int] = field(default_factory=dict)
    health_by_status: dict[str, int] = field(default_factory=dict)
    last_problem: str | None = None
    stream_bytes: int | None = None


def source_report(session: Session, now: datetime, hours: int = 24) -> list[SourceReport]:
    since = now - timedelta(hours=hours)
    reports = []
    for adapter in session.scalars(
        sa.select(SourceAdapter).order_by(SourceAdapter.source_adapter_id)
    ):
        sid = adapter.source_adapter_id
        docs = session.execute(
            sa.select(
                Document.published_at,
                Document.observed_at,
                Document.ingest_mode,
                Document.deleted_observed_at,
            ).where(Document.source_adapter_id == sid, Document.observed_at >= since)
        ).all()
        live_delays = [
            (observed - published).total_seconds()
            for published, observed, mode, _ in docs
            if mode == IngestMode.LIVE
        ]
        per_hour: dict[str, int] = {}
        for published, _, _, _ in docs:
            key = published.strftime("%Y-%m-%dT%H:00Z")
            per_hour[key] = per_hour.get(key, 0) + 1

        snapshots = session.scalar(
            sa.select(sa.func.count())
            .select_from(DocumentMetricSnapshot)
            .join(Document, Document.document_id == DocumentMetricSnapshot.document_id)
            .where(Document.source_adapter_id == sid, DocumentMetricSnapshot.observed_at >= since)
        )
        health = session.scalars(
            sa.select(SourceHealth)
            .where(SourceHealth.source_adapter_id == sid, SourceHealth.window_start >= since)
            .order_by(SourceHealth.window_start)
        ).all()
        by_status: dict[str, int] = {}
        stream_bytes: int | None = None
        last_problem = None
        for row in health:
            by_status[row.status.value] = by_status.get(row.status.value, 0) + 1
            if row.status.value != "ok" and row.note:
                last_problem = row.note
            if row.note and row.note.startswith("{"):
                try:
                    note = json.loads(row.note)
                except ValueError:
                    continue
                if isinstance(note.get("bytes"), int):
                    # 스트림 수집기는 누적 바이트를 남기므로 마지막 값이 합계다
                    stream_bytes = note["bytes"]

        reports.append(
            SourceReport(
                source_adapter_id=sid,
                access_status=adapter.access_status.value,
                documents_in_window=len(docs),
                live=sum(1 for d in docs if d.ingest_mode == IngestMode.LIVE),
                backfill=sum(1 for d in docs if d.ingest_mode == IngestMode.BACKFILL),
                deleted=sum(1 for d in docs if d.deleted_observed_at is not None),
                snapshots=snapshots or 0,
                median_delay_seconds=statistics.median(live_delays) if live_delays else None,
                per_hour=dict(sorted(per_hour.items())),
                health_by_status=by_status,
                last_problem=last_problem,
                stream_bytes=stream_bytes,
            )
        )
    return reports


def render(reports: list[SourceReport]) -> str:
    return json.dumps([asdict(r) for r in reports], ensure_ascii=False, indent=2)

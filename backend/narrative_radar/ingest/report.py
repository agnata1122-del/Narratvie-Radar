"""수집 현황 요약. M2(수집 가능성 확인)와 포워드 수집 점검에 쓴다."""

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.core.clock import ensure_utc
from narrative_radar.db.models import Document, DocumentMetricSnapshot, SourceAdapter, SourceHealth
from narrative_radar.schemas.enums import IngestMode, SourceAccessStatus, SourceHealthStatus


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


@dataclass
class SourceCheck:
    source_adapter_id: str
    ok: bool
    reason: str


def verify_sources(
    session: Session, now: datetime, expected: list[str], max_age: timedelta
) -> list[SourceCheck]:
    """운영 점검: 켜져 있어야 할 소스가 live이고, max_age 안에 정상(ok) 수집 기록이 있는가.

    정기 실행의 성공 여부와 별개로 소스마다 판단한다. 소스 단계는 실패해도 다음으로 넘어가므로
    실행 성공만으로는 소스가 정상인지 알 수 없다.
    """
    checks = []
    for sid in expected:
        adapter = session.get(SourceAdapter, sid)
        if adapter is None:
            checks.append(SourceCheck(sid, False, "unknown source"))
            continue
        if adapter.access_status != SourceAccessStatus.LIVE or not adapter.live_enabled:
            reason = f"{adapter.access_status.value}: {adapter.status_reason or ''}".strip()
            checks.append(SourceCheck(sid, False, reason[:200]))
            continue
        last_ok = session.scalar(
            sa.select(sa.func.max(SourceHealth.window_end)).where(
                SourceHealth.source_adapter_id == sid, SourceHealth.status == SourceHealthStatus.OK
            )
        )
        if last_ok is None or now - ensure_utc(last_ok) > max_age:
            seen = ensure_utc(last_ok).isoformat() if last_ok else "never"
            checks.append(SourceCheck(sid, False, f"no ok collection since {seen}"))
            continue
        checks.append(SourceCheck(sid, True, f"ok at {ensure_utc(last_ok).isoformat()}"))
    return checks

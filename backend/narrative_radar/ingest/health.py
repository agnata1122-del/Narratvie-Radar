"""수집 상태 기록. 기록이 없는 구간은 관측 공백으로 본다 (DECISIONS D10)."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from narrative_radar.core.clock import Clock, ensure_utc
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import SourceHealth
from narrative_radar.schemas.enums import SourceHealthStatus


def record_health(
    session: Session,
    clock: Clock,
    source_adapter_id: str,
    window_start: datetime,
    window_end: datetime,
    status: SourceHealthStatus,
    *,
    requests: int = 0,
    successes: int = 0,
    failures: int = 0,
    documents_listed: int = 0,
    documents_fetched: int = 0,
    note: str | None = None,
) -> SourceHealth:
    start, end = ensure_utc(window_start), ensure_utc(window_end)
    if end <= start:
        end = start + timedelta(microseconds=1)
    row = SourceHealth(
        health_id=new_id("shl", start),
        source_adapter_id=source_adapter_id,
        window_start=start,
        window_end=end,
        status=status,
        requests=requests,
        successes=successes,
        failures=failures,
        documents_listed=documents_listed,
        documents_fetched=documents_fetched,
        note=note,
        recorded_at=clock.now(),
    )
    session.add(row)
    return row

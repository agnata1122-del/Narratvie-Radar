"""수집을 해도 되는지 판단하고, 소스 상태를 바꾼다.

수집 조건: 전체 스위치(NR_LIVE_COLLECTION_ENABLED) + 소스별 live_enabled + 상태가 live.
"""

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.collectors.guard import TripKind
from narrative_radar.core.clock import Clock
from narrative_radar.core.config import Settings
from narrative_radar.db.models import SourceAdapter
from narrative_radar.schemas.enums import SourceAccessStatus


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str


def can_collect(settings: Settings, adapter: SourceAdapter) -> GateDecision:
    if not settings.live_collection_enabled:
        return GateDecision(False, "global switch NR_LIVE_COLLECTION_ENABLED is off")
    if not adapter.live_enabled:
        return GateDecision(False, f"{adapter.source_adapter_id}: live_enabled is off")
    if adapter.access_status != SourceAccessStatus.LIVE:
        return GateDecision(
            False, f"{adapter.source_adapter_id}: status is {adapter.access_status.value}"
        )
    if settings.author_hash_salt is None:
        return GateDecision(False, "NR_AUTHOR_HASH_SALT is not set")
    return GateDecision(True, "ok")


def get_adapter(session: Session, source_adapter_id: str) -> SourceAdapter:
    adapter = session.get(SourceAdapter, source_adapter_id)
    if adapter is None:
        known = ", ".join(session.scalars(sa.select(SourceAdapter.source_adapter_id)))
        raise KeyError(f"unknown source {source_adapter_id!r} (known: {known})")
    return adapter


def set_status(
    session: Session,
    source_adapter_id: str,
    status: SourceAccessStatus,
    reason: str,
    clock: Clock,
    live_enabled: bool | None = None,
) -> SourceAdapter:
    adapter = get_adapter(session, source_adapter_id)
    adapter.access_status = status
    adapter.status_reason = reason
    if live_enabled is not None:
        adapter.live_enabled = live_enabled
    adapter.updated_at = clock.now()
    return adapter


AUTO_STOP_STATUSES = frozenset({SourceAccessStatus.BLOCKED, SourceAccessStatus.STOPPED})


def auto_stop(
    session: Session, source_adapter_id: str, kind: TripKind, reason: str, clock: Clock
) -> None:
    """수집 중 문제가 생겼을 때 즉시 호출한다. live_enabled도 끈다:
    사람이 원인을 확인하고 `nr sources reset` → `enable` 하기 전에는 다시 수집하지 않는다."""
    status = SourceAccessStatus.BLOCKED if kind == TripKind.BLOCKED else SourceAccessStatus.STOPPED
    set_status(session, source_adapter_id, status, reason, clock, live_enabled=False)

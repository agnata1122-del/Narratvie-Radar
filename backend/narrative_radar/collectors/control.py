"""시스템 전체 긴급 중단 스위치 (DECISIONS D25).

환경변수 NR_LIVE_COLLECTION_ENABLED와 별개로, DB에 둔 스위치라 실행 중인 환경을 바꾸지 않고도
`nr emergency stop`으로 모든 발견·수집을 멈출 수 있다. 켜져 있는 동안은 어떤 수집도 시작하지 않고,
도는 중인 반복도 다음 요청 전에 멈춘다.
"""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.core.clock import Clock
from narrative_radar.db.models import ControlFlag

EMERGENCY_STOP = "emergency_stop"


def emergency_stop_reason(session: Session) -> str | None:
    flag = session.get(ControlFlag, EMERGENCY_STOP)
    if flag is None or not flag.enabled:
        return None
    return flag.reason or "emergency stop is on"


def set_emergency_stop(session: Session, clock: Clock, on: bool, reason: str) -> None:
    flag = session.get(ControlFlag, EMERGENCY_STOP)
    if flag is None:
        flag = ControlFlag(key=EMERGENCY_STOP, enabled=on, reason=reason, updated_at=clock.now())
        session.add(flag)
    else:
        flag.enabled = on
        flag.reason = reason
        flag.updated_at = clock.now()
    session.flush()


def all_flags(session: Session) -> list[ControlFlag]:
    return list(session.scalars(sa.select(ControlFlag).order_by(ControlFlag.key)))

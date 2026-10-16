"""시간은 항상 주입받는다.

`available_at`(그 시점에 시스템이 알 수 있었는지)이 섀도 테스트와 과거 상태 복원의 기준이므로,
코드 어디에서도 `datetime.now()`를 직접 부르지 않고 Clock을 통해 시각을 얻는다.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """테스트용. advance()로만 시간이 흐른다."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._now = start.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def ensure_utc(value: datetime) -> datetime:
    """시간대가 없는 datetime은 받지 않는다. 출처 시각을 추측해서 붙이면 안 되기 때문이다."""
    if value.tzinfo is None:
        raise ValueError(f"naive datetime is not allowed: {value!r}")
    return value.astimezone(UTC)

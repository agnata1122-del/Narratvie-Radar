import time
from collections.abc import Callable


class MinIntervalLimiter:
    """요청 사이에 최소 간격을 강제한다 (DATA_POLICY 2). 시계와 sleep은 테스트를 위해 주입한다."""

    def __init__(
        self,
        min_interval_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be >= 0")
        self.min_interval = min_interval_seconds
        self._monotonic = monotonic
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self.min_interval - (self._monotonic() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._monotonic()

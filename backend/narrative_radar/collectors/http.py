"""수집기가 쓰는 유일한 HTTP 클라이언트. DATA_POLICY의 규칙을 여기서 강제한다.

- 모든 요청 전에 차단 상태를 확인하고 최소 간격을 기다린다.
- 정직한 User-Agent를 쓰고 브라우저로 위장하지 않는다.
- robots.txt를 확인해 금지된 경로는 요청하지 않는다. Crawl-delay가 더 길면 그것을 따른다.
- GET만 지원한다. 글쓰기·로그인 같은 요청은 만들 수 없다.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from narrative_radar.collectors.guard import BlockGuard
from narrative_radar.collectors.rate_limit import MinIntervalLimiter

DEFAULT_MIN_INTERVAL_SECONDS = 3.0


class RobotsDisallowed(RuntimeError):
    """robots.txt가 금지한 경로."""


class RobotsUnavailable(RuntimeError):
    """robots.txt를 확인할 수 없어(5xx·네트워크 오류) 요청하지 않음."""


@dataclass
class RequestStats:
    requests: int = 0
    successes: int = 0
    failures: int = 0


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        limiter: MinIntervalLimiter | None = None,
        guard: BlockGuard | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if "mozilla" in user_agent.lower():
            raise ValueError("user agent must identify this project, not impersonate a browser")
        self.user_agent = user_agent
        self.limiter = limiter or MinIntervalLimiter(DEFAULT_MIN_INTERVAL_SECONDS)
        self.guard = guard or BlockGuard()
        self.stats = RequestStats()
        self._robots: dict[str, RobotFileParser] = {}
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        self.guard.check()
        robots = self._robots_for(url)
        if not robots.can_fetch(self.user_agent, url):
            raise RobotsDisallowed(url)
        delay = robots.crawl_delay(self.user_agent)
        if delay is not None and float(delay) > self.limiter.min_interval:
            self.limiter.min_interval = float(delay)
        return self._send(url, params)

    def _send(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        self.guard.check()
        self.limiter.wait()
        self.stats.requests += 1
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError:
            self.stats.failures += 1
            raise
        self.guard.observe(response)
        if response.is_success and not self.guard.tripped:
            self.stats.successes += 1
        else:
            self.stats.failures += 1
        return response

    def _robots_for(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        cached = self._robots.get(origin)
        if cached is not None:
            return cached

        parser = RobotFileParser()
        try:
            response = self._send(f"{origin}/robots.txt")
        except httpx.HTTPError as e:
            raise RobotsUnavailable(f"{origin}/robots.txt: {e}") from e
        self.guard.check()  # 401/403/429 등은 guard가 이미 차단으로 처리했다
        if response.status_code >= 500:
            raise RobotsUnavailable(f"{origin}/robots.txt: HTTP {response.status_code}")
        if response.status_code >= 400:
            parser.parse([])  # 없음(404 등) = 제한 없음 (RFC 9309)
        else:
            parser.parse(response.text.splitlines())
        self._robots[origin] = parser
        return parser

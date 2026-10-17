"""범용 웹 수집기의 HTTP 단계 (DECISIONS D25, DATA_POLICY 3-1).

한 URL을 가져오고 결과를 사이트 단위로 판정한다. 어느 사이트를 허용할지는 호출자(ingest/web.py)가
사이트 정책으로 정하고, 여기서는 요청 하나하나의 안전을 지킨다.

- http(s)와 기본 포트(80·443)만. 사용자 정보가 든 URL은 거부한다.
- 호스트를 직접 해석해 내부망·사설·루프백·링크 로컬 등 공인 주소가 아닌 곳이면 요청하지 않는다.
- 리다이렉트는 자동으로 따라가지 않는다. 단계마다 위 검사를 다시 하고, 다른 사이트로 가면
  그 사이트가 허용됐는지 확인한다. 최대 횟수를 넘으면 멈춘다. 로그인 페이지로 가면 접근 제한이다.
- robots.txt를 먼저 확인하고 Crawl-delay를 따른다. 같은 사이트에 다시 요청하기까지 최소 간격을 둔다.
- HTML만 받고 크기 상한을 넘으면 읽기를 멈춘다. 쿠키를 남기지 않는다(로그인 상태를 만들지 않는다).
- 판정: 접근 거부·수집 금지·접근 제한 신호 → BLOCKED(그 사이트 차단), 5xx·시간 초과·연결 오류 →
  TRANSIENT(제한적 재시도), 우리 안전 규칙·없는 글·HTML 아님 → REJECTED(이 URL만 포기),
  허용되지 않은 사이트로 가는 리다이렉트 → SKIPPED.
"""

import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from narrative_radar.collectors.extract import (
    PageContent,
    decode_html,
    extract_page,
    looks_like_challenge,
    robots_directives,
)
from narrative_radar.collectors.guard import LOGIN_PATH_MARKERS
from narrative_radar.discovery.urls import site_of
from narrative_radar.schemas.enums import FetchOutcome

HTML_TYPES = ("text/html", "application/xhtml+xml")
REFUSAL_STATUS = frozenset({401, 403, 429, 451})  # 접근 거부·수집 금지·접근 제한
GONE_STATUS = frozenset({404, 410})
REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
DEFAULT_PORTS = {"http": 80, "https": 443}
NO_COLLECTION_DIRECTIVES = frozenset({"noai"})
MAX_ROBOTS_BYTES = 500_000
MAX_CRAWL_DELAY = 120.0

Resolver = Callable[[str], list[str]]


def system_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def unsafe_address(address: str) -> str | None:
    """공인 주소가 아니면 그 이유."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return f"unparseable address {address!r}"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if not ip.is_global or ip.is_multicast:
        return f"non-public address {ip}"
    return None


@dataclass(frozen=True)
class RequestLog:
    site: str
    url: str
    outcome: FetchOutcome
    status_code: int | None
    detail: str
    robots: bool = False


@dataclass(frozen=True)
class FetchResult:
    outcome: FetchOutcome
    site: str  # 판정이 해당하는 사이트 (리다이렉트로 바뀔 수 있다)
    url: str  # 마지막으로 다룬 주소
    detail: str = ""
    status_code: int | None = None
    page: PageContent | None = None


class _Outcome(Exception):
    def __init__(self, result: FetchResult) -> None:
        super().__init__(result.detail)
        self.result = result


class SiteIntervals:
    """같은 사이트에 다시 요청하기까지 최소 간격. 시계와 sleep은 테스트를 위해 주입한다."""

    def __init__(
        self,
        min_interval: float,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._monotonic = monotonic
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self.delay: dict[str, float] = {}  # robots.txt Crawl-delay

    def wait(self, site: str) -> None:
        interval = max(self.min_interval, self.delay.get(site, 0.0))
        last = self._last.get(site)
        if last is not None:
            remaining = interval - (self._monotonic() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last[site] = self._monotonic()


class SafeWebFetcher:
    def __init__(
        self,
        user_agent: str,
        intervals: SiteIntervals,
        max_bytes: int = 2_000_000,
        max_redirects: int = 3,
        timeout_seconds: float = 20.0,
        resolver: Resolver = system_resolver,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if "mozilla" in user_agent.lower():
            raise ValueError("user agent must identify this project, not impersonate a browser")
        self.user_agent = user_agent
        self.intervals = intervals
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.resolver = resolver
        self._robots: dict[str, RobotFileParser] = {}
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def fetch(
        self,
        url: str,
        site_allowed: Callable[[str], str | None],
        log: Callable[[RequestLog], None],
    ) -> FetchResult:
        """site_allowed(site): 허용되면 None, 아니면 이유. log: 요청마다 호출된다."""
        try:
            return self._fetch(url, site_allowed, log)
        except _Outcome as o:
            return o.result

    # --- 내부 -----------------------------------------------------------------------------

    def _fetch(
        self,
        url: str,
        site_allowed: Callable[[str], str | None],
        log: Callable[[RequestLog], None],
    ) -> FetchResult:
        start_site = site_of(url)
        current = url
        for _hop in range(self.max_redirects + 1):
            site = site_of(current)
            self._check_url(current, site, log)
            if site != start_site and (why := site_allowed(site)) is not None:
                result = FetchResult(
                    FetchOutcome.SKIPPED, site, current, f"redirect to {site}: {why}"
                )
                log(RequestLog(site, current, result.outcome, None, result.detail))
                return result
            self._check_robots(current, site, log)
            response = self._request(current, site, log)
            if response.status_code in REDIRECT_STATUS:
                response.close()
                target = urljoin(current, response.headers.get("location", ""))
                log(
                    RequestLog(site, current, FetchOutcome.OK, response.status_code, f"-> {target}")
                )
                if any(m in target.lower() for m in LOGIN_PATH_MARKERS):
                    return self._done(
                        log,
                        FetchOutcome.BLOCKED,
                        site,
                        current,
                        response.status_code,
                        f"redirected to login page: {target}",
                    )
                current = target
                continue
            return self._read(response, site, current, log)
        return self._done(
            log,
            FetchOutcome.REJECTED,
            site_of(current),
            current,
            None,
            f"more than {self.max_redirects} redirects",
        )

    def _check_url(
        self, url: str, site: str, log: Callable[[RequestLog], None], robots: bool = False
    ) -> None:
        def reject(detail: str) -> NoReturn:
            self._fail(log, FetchOutcome.REJECTED, site, url, None, detail, robots)

        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError as e:
            reject(f"bad url: {e}")
        scheme = parts.scheme.lower()
        if scheme not in DEFAULT_PORTS or not parts.hostname:
            reject("not an http(s) url")
        if parts.username or parts.password:
            reject("credentials in url")
        if port not in (None, DEFAULT_PORTS[scheme]):
            reject(f"non-default port {port}")
        try:
            addresses = self.resolver(parts.hostname)
        except OSError as e:
            self._fail(
                log, FetchOutcome.TRANSIENT, site, url, None, f"dns lookup failed: {e}", robots
            )
        if not addresses:
            self._fail(log, FetchOutcome.TRANSIENT, site, url, None, "dns returned nothing", robots)
        for address in addresses:
            if (why := unsafe_address(address)) is not None:
                reject(why)

    def _request(
        self, url: str, site: str, log: Callable[[RequestLog], None], robots: bool = False
    ) -> httpx.Response:
        self.intervals.wait(site)
        try:
            return self._client.send(self._client.build_request("GET", url), stream=True)
        except httpx.ProxyError as e:
            self._fail(log, FetchOutcome.TRANSIENT, site, url, None, f"proxy refused: {e}", robots)
        except httpx.TransportError as e:
            detail = f"{type(e).__name__}: {e}"
            self._fail(log, FetchOutcome.TRANSIENT, site, url, None, detail, robots)
        finally:
            self._client.cookies.clear()  # 로그인 상태나 추적 쿠키를 남기지 않는다

    def _read_body(
        self,
        response: httpx.Response,
        site: str,
        url: str,
        log: Callable[[RequestLog], None],
        limit: int,
        robots: bool = False,
    ) -> bytes:
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            response.close()
            self._fail(
                log,
                FetchOutcome.REJECTED,
                site,
                url,
                response.status_code,
                f"too large ({declared} bytes)",
                robots,
            )
        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > limit:
                    self._fail(
                        log,
                        FetchOutcome.REJECTED,
                        site,
                        url,
                        response.status_code,
                        f"too large (> {limit} bytes)",
                        robots,
                    )
                chunks.append(chunk)
        except httpx.TransportError as e:
            self._fail(
                log,
                FetchOutcome.TRANSIENT,
                site,
                url,
                response.status_code,
                f"{type(e).__name__} while reading",
                robots,
            )
        finally:
            response.close()
        return b"".join(chunks)

    def _check_robots(self, url: str, site: str, log: Callable[[RequestLog], None]) -> None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(origin)
        if parser is None:
            parser = self._load_robots(origin, site, log)
            self._robots[origin] = parser
            delay = parser.crawl_delay(self.user_agent)
            if delay is not None:
                self.intervals.delay[site] = min(float(delay), MAX_CRAWL_DELAY)
        if parser.can_fetch(self.user_agent, url):
            return
        if not parser.can_fetch(self.user_agent, f"{origin}/"):
            self._fail(
                log, FetchOutcome.BLOCKED, site, url, None, "robots.txt disallows this agent"
            )
        self._fail(log, FetchOutcome.REJECTED, site, url, None, "robots.txt disallows this path")

    def _load_robots(
        self, origin: str, site: str, log: Callable[[RequestLog], None]
    ) -> RobotFileParser:
        robots_url = f"{origin}/robots.txt"
        current = robots_url
        for _hop in range(self.max_redirects + 1):
            self._check_url(current, site_of(current), log, robots=True)
            response = self._request(current, site, log, robots=True)
            status = response.status_code
            if status in REDIRECT_STATUS:
                response.close()
                current = urljoin(current, response.headers.get("location", ""))
                continue
            parser = RobotFileParser()
            if status in REFUSAL_STATUS:
                response.close()
                self._fail(
                    log,
                    FetchOutcome.BLOCKED,
                    site,
                    current,
                    status,
                    f"HTTP {status} for robots.txt",
                    robots=True,
                )
            if status >= 500:
                response.close()
                # RFC 9309: robots.txt에 닿을 수 없으면 전부 금지로 본다 → 이번에는 가져오지 않는다
                self._fail(
                    log,
                    FetchOutcome.TRANSIENT,
                    site,
                    current,
                    status,
                    f"robots.txt unreachable (HTTP {status})",
                    robots=True,
                )
            if status >= 400:
                response.close()
                parser.parse([])  # 없음 = 제한 없음
            else:
                body = self._read_body(response, site, current, log, MAX_ROBOTS_BYTES, robots=True)
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
            log(RequestLog(site, current, FetchOutcome.OK, status, "robots.txt", robots=True))
            return parser
        self._fail(
            log,
            FetchOutcome.TRANSIENT,
            site,
            robots_url,
            None,
            "too many robots.txt redirects",
            robots=True,
        )

    def _read(
        self, response: httpx.Response, site: str, url: str, log: Callable[[RequestLog], None]
    ) -> FetchResult:
        status = response.status_code
        if status in REFUSAL_STATUS:
            response.close()
            return self._done(log, FetchOutcome.BLOCKED, site, url, status, f"HTTP {status}")
        if status in GONE_STATUS:
            response.close()
            return self._done(log, FetchOutcome.REJECTED, site, url, status, "gone")
        if status >= 500:
            body = self._read_body(response, site, url, log, self.max_bytes)
            html = decode_html(body, response.headers.get("content-type", ""))
            if looks_like_challenge(html, extract_page(html)):
                return self._done(log, FetchOutcome.BLOCKED, site, url, status, "challenge page")
            return self._done(log, FetchOutcome.TRANSIENT, site, url, status, f"HTTP {status}")
        if status != 200:
            response.close()
            return self._done(log, FetchOutcome.REJECTED, site, url, status, f"HTTP {status}")
        content_type = response.headers.get("content-type", "")
        if not content_type.lower().startswith(HTML_TYPES):
            response.close()
            return self._done(
                log, FetchOutcome.REJECTED, site, url, status, f"not html ({content_type})"
            )
        header_directives = robots_directives(response.headers.get("x-robots-tag", ""))
        if header_directives & NO_COLLECTION_DIRECTIVES:
            response.close()
            return self._done(log, FetchOutcome.BLOCKED, site, url, status, "X-Robots-Tag: noai")
        body = self._read_body(response, site, url, log, self.max_bytes)
        html = decode_html(body, content_type)
        page = extract_page(html)
        if looks_like_challenge(html, page):
            return self._done(log, FetchOutcome.BLOCKED, site, url, status, "challenge page")
        if page.robots & NO_COLLECTION_DIRECTIVES:
            return self._done(log, FetchOutcome.BLOCKED, site, url, status, "meta robots: noai")
        log(RequestLog(site, url, FetchOutcome.OK, status, f"{len(body)} bytes"))
        return FetchResult(FetchOutcome.OK, site, url, "", status, page)

    def _done(
        self,
        log: Callable[[RequestLog], None],
        outcome: FetchOutcome,
        site: str,
        url: str,
        status: int | None,
        detail: str,
    ) -> FetchResult:
        log(RequestLog(site, url, outcome, status, detail))
        return FetchResult(outcome, site, url, detail, status)

    def _fail(
        self,
        log: Callable[[RequestLog], None],
        outcome: FetchOutcome,
        site: str,
        url: str,
        status: int | None,
        detail: str,
        robots: bool = False,
    ) -> NoReturn:
        log(RequestLog(site, url, outcome, status, detail, robots=robots))
        raise _Outcome(FetchResult(outcome, site, url, detail, status))

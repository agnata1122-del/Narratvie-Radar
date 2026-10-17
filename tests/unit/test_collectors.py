import httpx
import pytest

from narrative_radar.collectors.author import AuthorHasher
from narrative_radar.collectors.guard import BlockGuard, CollectionBlocked, TripKind
from narrative_radar.collectors.http import PoliteClient, RobotsDisallowed
from narrative_radar.collectors.rate_limit import MinIntervalLimiter

UA = "NarrativeRadar/0.2 (+https://github.com/agnata1122-del/Narratvie-Radar)"
ROBOTS = "User-agent: *\nDisallow: /private\n"


class FakeTime:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def make_client(handler, min_interval=3.0, fake_time=None):
    fake_time = fake_time or FakeTime()
    limiter = MinIntervalLimiter(min_interval, fake_time.monotonic, fake_time.sleep)
    calls: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    client = PoliteClient(UA, limiter=limiter, transport=httpx.MockTransport(recording))
    return client, calls, fake_time


def site(pages: dict[str, httpx.Response], robots: str | int = ROBOTS):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            if isinstance(robots, int):
                return httpx.Response(robots)
            return httpx.Response(200, text=robots)
        return pages.get(request.url.path, httpx.Response(200, text="ok"))

    return handler


def test_limiter_enforces_minimum_interval():
    ft = FakeTime()
    limiter = MinIntervalLimiter(3.0, ft.monotonic, ft.sleep)
    limiter.wait()
    ft.t += 1.0
    limiter.wait()
    assert ft.slept == [pytest.approx(2.0)]
    ft.t += 5.0
    limiter.wait()
    assert ft.slept == [pytest.approx(2.0)]


def test_every_request_waits_including_robots_and_sends_honest_user_agent():
    client, calls, ft = make_client(site({}))
    client.get("https://example.com/a")
    client.get("https://example.com/b")
    assert [c.url.path for c in calls] == ["/robots.txt", "/a", "/b"]
    assert all(c.headers["user-agent"] == UA for c in calls)
    assert ft.slept == [pytest.approx(3.0), pytest.approx(3.0)]
    assert all(c.method == "GET" for c in calls)


def test_browser_impersonation_is_refused():
    with pytest.raises(ValueError):
        PoliteClient("Mozilla/5.0 (Windows NT 10.0)")


def test_robots_disallowed_path_is_never_requested():
    client, calls, _ = make_client(site({}))
    with pytest.raises(RobotsDisallowed):
        client.get("https://example.com/private/page")
    assert [c.url.path for c in calls] == ["/robots.txt"]


def test_robots_crawl_delay_raises_interval():
    client, _, ft = make_client(site({}, robots="User-agent: *\nCrawl-delay: 10\n"))
    client.get("https://example.com/a")
    client.get("https://example.com/b")
    assert ft.slept[-1] == pytest.approx(10.0)


def test_missing_robots_means_no_restriction():
    client, _, _ = make_client(site({}, robots=404))
    assert client.get("https://example.com/private/page").status_code == 200


def test_unreadable_robots_stops_collection_before_any_page_request():
    client, calls, _ = make_client(site({}, robots=503))
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/a")
    assert [c.url.path for c in calls] == ["/robots.txt"]
    assert client.guard.tripped_kind == TripKind.ERROR


@pytest.mark.parametrize("status", [401, 403, 429])
def test_block_status_stops_immediately_as_blocked(status):
    client, calls, _ = make_client(site({"/a": httpx.Response(status)}))
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/a")
    assert client.guard.tripped_kind == TripKind.BLOCKED
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/b")
    assert [c.url.path for c in calls] == ["/robots.txt", "/a"]


@pytest.mark.parametrize("status", [400, 405, 500, 502, 503])
def test_any_other_error_stops_on_first_occurrence(status):
    client, calls, _ = make_client(site({"/a": httpx.Response(status)}))
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/a")
    assert client.guard.tripped_kind == TripKind.ERROR
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/b")
    assert [c.url.path for c in calls] == ["/robots.txt", "/a"]
    assert client.stats.failures == 1


def test_network_error_stops_immediately():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        raise httpx.ConnectTimeout("timed out", request=request)

    client, calls, _ = make_client(handler)
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/a")
    assert client.guard.tripped_kind == TripKind.ERROR
    assert "ConnectTimeout" in client.guard.tripped_reason
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/b")
    assert len(calls) == 2


def test_captcha_page_stops_as_blocked():
    page = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        text="<html>자동입력 방지 문자를 입력하세요</html>",
    )
    client, _, _ = make_client(site({"/a": page}))
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/a")
    assert client.guard.tripped_kind == TripKind.BLOCKED
    assert "challenge" in client.guard.tripped_reason


def test_login_redirect_stops_as_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "https://example.com/login?next=/a"})
        return httpx.Response(200, text="login form")

    client, _, _ = make_client(handler)
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/a")
    assert client.guard.tripped_kind == TripKind.BLOCKED


def test_deleted_posts_are_not_treated_as_problems():
    client, _, _ = make_client(site({"/gone": httpx.Response(404)}))
    for _ in range(5):
        assert client.get("https://example.com/gone").status_code == 404
    assert not client.guard.tripped


def test_on_trip_is_called_once_with_kind_and_reason():
    seen: list[tuple[TripKind, str]] = []
    guard = BlockGuard(on_trip=lambda kind, reason: seen.append((kind, reason)))
    req = httpx.Request("GET", "https://example.com/x")
    guard.observe(httpx.Response(503, request=req))
    guard.observe(httpx.Response(403, request=req))
    guard.trip(TripKind.ERROR, "parse failed")
    assert len(seen) == 1
    assert seen[0][0] == TripKind.ERROR
    assert "503" in seen[0][1]


def test_author_hash_is_stable_salted_and_not_reversible_by_shape():
    a = AuthorHasher("s" * 32)
    b = AuthorHasher("t" * 32)
    h = a.hash("dcinside", "ㅇㅇ(1.234)")
    assert h == a.hash("dcinside", "ㅇㅇ(1.234)")
    assert h != b.hash("dcinside", "ㅇㅇ(1.234)")
    assert h != a.hash("naver", "ㅇㅇ(1.234)")
    assert len(h) == 64 and "1.234" not in h
    assert a.hash("dcinside", "   ") is None
    with pytest.raises(ValueError):
        AuthorHasher("short")


def _flaky(responses):
    """순서대로 응답(또는 예외)을 돌려준다. robots.txt는 없음(404)."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return handler


def _retrying(handler, retries=2):
    sleeps: list[float] = []
    client = PoliteClient(
        "NarrativeRadar/test",
        limiter=MinIntervalLimiter(0),
        transport=httpx.MockTransport(handler),
        transient_retries=retries,
        retry_backoff_seconds=(15.0, 45.0),
        sleep=sleeps.append,
    )
    return client, sleeps


def test_transient_errors_are_retried_a_limited_number_of_times():
    req = httpx.Request("GET", "https://example.com/x")
    client, sleeps = _retrying(
        _flaky(
            [
                httpx.RemoteProtocolError("disconnected", request=req),
                httpx.Response(503),
                httpx.Response(200, json={}),
            ]
        )
    )
    assert client.get("https://example.com/x").status_code == 200
    assert sleeps == [15.0, 45.0] and not client.guard.tripped

    client, sleeps = _retrying(_flaky([httpx.Response(502)] * 3))
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/x")
    assert client.guard.tripped_kind == TripKind.ERROR and len(sleeps) == 2


def test_block_signals_are_never_retried():
    client, sleeps = _retrying(_flaky([httpx.Response(429), httpx.Response(200)]))
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/x")
    assert client.guard.tripped_kind == TripKind.BLOCKED and sleeps == []


def test_default_client_still_stops_on_the_first_error():
    client, sleeps = _retrying(_flaky([httpx.Response(503), httpx.Response(200)]), retries=0)
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/x")
    assert sleeps == []

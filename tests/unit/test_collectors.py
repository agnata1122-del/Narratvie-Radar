import httpx
import pytest

from narrative_radar.collectors.author import AuthorHasher
from narrative_radar.collectors.guard import BlockGuard, CollectionBlocked
from narrative_radar.collectors.http import PoliteClient, RobotsDisallowed, RobotsUnavailable
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


def test_missing_robots_means_no_restriction_but_server_error_means_stop():
    client, _, _ = make_client(site({}, robots=404))
    assert client.get("https://example.com/private/page").status_code == 200

    client, calls, _ = make_client(site({}, robots=503))
    with pytest.raises(RobotsUnavailable):
        client.get("https://example.com/a")
    assert [c.url.path for c in calls] == ["/robots.txt"]


@pytest.mark.parametrize("status", [401, 403, 429])
def test_block_status_trips_guard_and_stops_all_further_requests(status):
    client, calls, _ = make_client(site({"/a": httpx.Response(status)}))
    client.get("https://example.com/a")
    assert client.guard.tripped
    with pytest.raises(CollectionBlocked):
        client.get("https://example.com/b")
    assert [c.url.path for c in calls] == ["/robots.txt", "/a"]


def test_captcha_page_trips_guard():
    page = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        text="<html>자동입력 방지 문자를 입력하세요</html>",
    )
    client, _, _ = make_client(site({"/a": page}))
    client.get("https://example.com/a")
    assert client.guard.tripped
    assert "challenge" in client.guard.tripped_reason


def test_login_redirect_trips_guard():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "https://example.com/login?next=/a"})
        return httpx.Response(200, text="login form")

    client, _, _ = make_client(handler)
    client.get("https://example.com/a")
    assert client.guard.tripped


def test_deleted_posts_do_not_trip_but_repeated_client_errors_do():
    pages = {"/gone": httpx.Response(404), "/bad": httpx.Response(400)}
    client, _, _ = make_client(site(pages))
    for _ in range(5):
        client.get("https://example.com/gone")
    assert not client.guard.tripped

    for _ in range(2):
        client.get("https://example.com/bad")
    assert not client.guard.tripped
    client.get("https://example.com/bad")
    assert client.guard.tripped


def test_server_errors_are_failures_not_blocks():
    client, _, _ = make_client(site({"/a": httpx.Response(503)}))
    for _ in range(5):
        client.get("https://example.com/a")
    assert not client.guard.tripped
    assert client.stats.failures == 5
    assert client.stats.requests == 6  # robots + 5


def test_guard_success_resets_client_error_streak():
    guard = BlockGuard(max_consecutive_client_errors=2)
    req = httpx.Request("GET", "https://example.com/x")
    guard.observe(httpx.Response(400, request=req))
    guard.observe(httpx.Response(200, request=req, text=""))
    guard.observe(httpx.Response(400, request=req))
    assert not guard.tripped


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

"""범용 수집기의 HTTP 단계와 본문 추출 (DECISIONS D25).

HTML과 응답은 형식 확인용으로 직접 작성한 예시이고, 예시용 도메인(example.com 등)만 쓴다
(DECISIONS D0 예외). 실제 네트워크와 DNS는 쓰지 않는다.
"""

from datetime import UTC, datetime

import httpx
import pytest

from narrative_radar.collectors.extract import (
    decode_html,
    extract_page,
    looks_like_challenge,
    robots_directives,
)
from narrative_radar.collectors.web import SafeWebFetcher, SiteIntervals, unsafe_address
from narrative_radar.schemas.enums import FetchOutcome

PUBLIC_IP = "93.184.216.34"
BODY = " ".join(["This example paragraph has enough words to count as article text."] * 4)

ARTICLE = f"""<!doctype html><html lang="en"><head>
<title>Example page title</title>
<meta property="og:title" content="Example headline">
<meta property="article:published_time" content="2026-10-16T01:30:00+00:00">
<script src="https://www.example.net/recaptcha/api.js"></script>
</head><body>
<nav><a href="/">Home</a> <a href="/news">News navigation link text that is long</a></nav>
<header><p>Site header paragraph that should not be part of the article body</p></header>
<article><h1>Example headline</h1><p>{BODY}</p>
<p>Second paragraph with more example words in it.</p>
<aside><p>Related links sidebar paragraph that should be skipped entirely</p></aside></article>
<footer><p>Footer paragraph with copyright text that should be skipped</p></footer>
</body></html>"""


# --- 본문 추출 ---------------------------------------------------------------------------


def test_extract_takes_article_text_and_metadata():
    page = extract_page(ARTICLE)
    assert page.title == "Example headline"
    assert page.published_at == datetime(2026, 10, 16, 1, 30, tzinfo=UTC)
    assert page.lang == "en"
    assert page.text.startswith("Example headline\nThis example paragraph")
    assert "Second paragraph" in page.text
    for skipped in ("navigation", "header paragraph", "sidebar", "Footer"):
        assert skipped not in page.text
    assert not looks_like_challenge(
        ARTICLE, page
    )  # 댓글 폼 reCAPTCHA 스크립트는 차단 페이지가 아니다


def test_extract_falls_back_to_json_ld_and_ignores_naive_times():
    html = f"""<html><head><script type="application/ld+json">
    {{"@graph": [{{"@type": "WebSite"}}, {{"@type": "NewsArticle", "headline": "LD headline",
      "datePublished": "2026-10-15T09:00:00+09:00"}}]}}</script>
    <meta name="date" content="2026-10-15 09:00:00"></head>
    <body><main><p>{BODY}</p></main></body></html>"""
    page = extract_page(html)
    assert page.title == "LD headline"
    assert page.published_at == datetime(2026, 10, 15, 0, 0, tzinfo=UTC)
    assert page.text == BODY


def test_robots_directives_only_for_everyone_or_us():
    assert robots_directives("noindex, noai") == {"noindex", "noai"}
    assert robots_directives("otherbot: noai, narrativeradar: nofollow") == {"nofollow"}
    html = '<html><head><meta name="robots" content="noai"></head><body></body></html>'
    assert "noai" in extract_page(html).robots
    html = '<html><head><meta name="otherbot" content="noai"></head><body></body></html>'
    assert not extract_page(html).robots


def test_decode_uses_header_then_meta_charset():
    korean = "<html><head><meta charset='euc-kr'></head><body><p>한국어 예시 문장</p></body></html>"
    raw = korean.encode("euc-kr")
    assert "한국어 예시 문장" in decode_html(raw, "text/html")
    assert "한국어 예시 문장" in decode_html(raw, "text/html; charset=EUC-KR")
    assert decode_html(b"plain", "text/html; charset=unknown-x") == "plain"


def test_challenge_pages_are_recognised():
    cf = "<html><head><title>Just a moment...</title></head><body>Checking</body></html>"
    assert looks_like_challenge(cf, extract_page(cf))
    short = "<html><body><p>Please complete the CAPTCHA to continue to the site</p></body></html>"
    assert looks_like_challenge(short, extract_page(short))


def test_only_public_addresses_are_allowed():
    for bad in (
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "::1",
        "::ffff:10.0.0.1",
        "fd00::1",
        "0.0.0.0",
        "224.0.0.1",
    ):
        assert unsafe_address(bad), bad
    assert unsafe_address(PUBLIC_IP) is None
    assert unsafe_address("2606:2800:220:1:248:1893:25c8:1946") is None


# --- 가져오기 ------------------------------------------------------------------------------


class Site:
    """경로별 응답. robots.txt는 기본 404(제한 없음)."""

    def __init__(self, routes):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.url.host}{request.url.path}"
        make = self.routes.get(key)
        if make is None:
            return httpx.Response(404)
        return make() if callable(make) else make


def html(body=ARTICLE, **headers):
    return httpx.Response(
        200, text=body, headers={"content-type": "text/html; charset=utf-8", **headers}
    )


def fetcher(site, resolver=None, intervals=None, **kw):
    return SafeWebFetcher(
        "NarrativeRadar/test",
        intervals or SiteIntervals(0),
        resolver=resolver
        or (lambda host: ["10.0.0.5"] if host.startswith("internal") else [PUBLIC_IP]),
        transport=httpx.MockTransport(site),
        **kw,
    )


def run(f, url, allowed=lambda site: None):
    logs = []
    return f.fetch(url, allowed, logs.append), logs


def test_ok_page_is_read_and_logged():
    site = Site({"example.com/a": html()})
    result, logs = run(fetcher(site), "https://example.com/a")
    assert result.outcome == FetchOutcome.OK and result.page.title == "Example headline"
    assert [(entry.url, entry.outcome, entry.robots) for entry in logs] == [
        ("https://example.com/robots.txt", FetchOutcome.OK, True),
        ("https://example.com/a", FetchOutcome.OK, False),
    ]
    assert site.requests[-1].headers["user-agent"] == "NarrativeRadar/test"


def test_private_addresses_are_never_requested():
    site = Site({})
    result, logs = run(fetcher(site), "https://internal.example/a")
    assert result.outcome == FetchOutcome.REJECTED and "non-public" in result.detail
    assert site.requests == [] and logs[0].outcome == FetchOutcome.REJECTED
    for url in ("ftp://example.com/x", "https://example.com:8443/x", "https://u:p@example.com/x"):
        assert run(fetcher(site), url)[0].outcome == FetchOutcome.REJECTED
    assert site.requests == []


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (403, FetchOutcome.BLOCKED),
        (429, FetchOutcome.BLOCKED),
        (401, FetchOutcome.BLOCKED),
        (451, FetchOutcome.BLOCKED),
        (503, FetchOutcome.TRANSIENT),
        (500, FetchOutcome.TRANSIENT),
        (404, FetchOutcome.REJECTED),
        (400, FetchOutcome.REJECTED),
    ],
)
def test_status_codes_split_refusals_from_temporary_errors(status, outcome):
    site = Site({"example.com/a": httpx.Response(status, text="example")})
    assert run(fetcher(site), "https://example.com/a")[0].outcome == outcome


def test_challenge_behind_5xx_is_a_refusal():
    cf = "<html><head><title>Just a moment...</title></head><body></body></html>"
    site = Site(
        {"example.com/a": httpx.Response(503, text=cf, headers={"content-type": "text/html"})}
    )
    assert run(fetcher(site), "https://example.com/a")[0].outcome == FetchOutcome.BLOCKED


def test_connection_errors_are_temporary():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    result, _ = run(fetcher(boom), "https://example.com/a")
    assert result.outcome == FetchOutcome.TRANSIENT


def test_redirects_are_checked_hop_by_hop():
    def redirect(to):
        return httpx.Response(302, headers={"location": to})

    site = Site(
        {
            "example.com/a": redirect("/b"),
            "example.com/b": html(),
            "example.com/inside": redirect("https://internal.example/x"),
            "example.com/away": redirect("https://other.example.org/x"),
            "other.example.org/x": html(),
            "example.com/login": redirect("https://example.com/login?next=/a"),
            "example.com/loop": redirect("/loop"),
        }
    )
    f = fetcher(site)
    ok, logs = run(f, "https://example.com/a")
    assert ok.outcome == FetchOutcome.OK and ok.url == "https://example.com/b"
    assert run(f, "https://example.com/inside")[0].outcome == FetchOutcome.REJECTED
    skipped, _ = run(f, "https://example.com/away", allowed=lambda s: "site is pending_review")
    assert skipped.outcome == FetchOutcome.SKIPPED and skipped.site == "other.example.org"
    assert (
        run(f, "https://example.com/away")[0].outcome == FetchOutcome.OK
    )  # 허용된 사이트면 따라간다
    assert run(f, "https://example.com/login")[0].outcome == FetchOutcome.BLOCKED
    looped, _ = run(f, "https://example.com/loop")
    assert looped.outcome == FetchOutcome.REJECTED and "redirects" in looped.detail


def test_robots_and_noai_are_respected():
    disallow_all = httpx.Response(200, text="User-agent: *\nDisallow: /\n")
    partial = httpx.Response(200, text="User-agent: *\nDisallow: /private\nCrawl-delay: 30\n")
    sleeps: list[float] = []
    clock = iter(range(0, 1000, 1))
    intervals = SiteIntervals(0, monotonic=lambda: float(next(clock)), sleep=sleeps.append)
    site = Site(
        {
            "example.com/robots.txt": disallow_all,
            "example.org/robots.txt": partial,
            "example.org/private/x": html(),
            "example.org/public": html(),
            "example.net/robots.txt": httpx.Response(403),
            "example.edu/header": html(**{"x-robots-tag": "noai"}),
            "example.edu/meta": html(
                '<html><head><meta name="robots" content="noai"></head><body></body></html>'
            ),
        }
    )
    f = fetcher(site, intervals=intervals)
    assert run(f, "https://example.com/a")[0].outcome == FetchOutcome.BLOCKED
    private, _ = run(f, "https://example.org/private/x")
    assert private.outcome == FetchOutcome.REJECTED and "path" in private.detail
    assert run(f, "https://example.org/public")[0].outcome == FetchOutcome.OK
    assert sleeps and max(sleeps) > 25  # Crawl-delay 30초를 따른다
    assert run(f, "https://example.net/a")[0].outcome == FetchOutcome.BLOCKED
    assert run(f, "https://example.edu/header")[0].outcome == FetchOutcome.BLOCKED
    assert run(f, "https://example.edu/meta")[0].outcome == FetchOutcome.BLOCKED


def test_only_html_within_size_limit():
    site = Site(
        {
            "example.com/pdf": httpx.Response(
                200, content=b"%PDF", headers={"content-type": "application/pdf"}
            ),
            "example.com/big": html("<p>" + "x" * 5000 + "</p>"),
        }
    )
    f = fetcher(site, max_bytes=1000)
    assert run(f, "https://example.com/pdf")[0].outcome == FetchOutcome.REJECTED
    big, _ = run(f, "https://example.com/big")
    assert big.outcome == FetchOutcome.REJECTED and "too large" in big.detail


def test_no_cookies_are_kept_between_requests():
    site = Site(
        {
            "example.com/a": lambda: html(**{"set-cookie": "session=abc; Path=/"}),
            "example.com/b": html(),
        }
    )
    f = fetcher(site)
    run(f, "https://example.com/a")
    run(f, "https://example.com/b")
    assert "cookie" not in site.requests[-1].headers


def test_same_site_requests_are_spaced():
    sleeps: list[float] = []
    now = [0.0]
    intervals = SiteIntervals(10, monotonic=lambda: now[0], sleep=lambda s: sleeps.append(s))
    intervals.wait("example.com")
    now[0] = 3.0
    intervals.wait("example.com")
    intervals.wait("example.org")  # 다른 사이트는 기다리지 않는다
    assert sleeps == [7.0]


def test_browser_impersonation_is_refused():
    with pytest.raises(ValueError):
        SafeWebFetcher("Mozilla/5.0", SiteIntervals(0))

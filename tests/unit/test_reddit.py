"""형식 검증용 예시 응답.

Arctic Shift API의 공개 응답 형식을 따라 직접 작성했다 (DECISIONS D0 예외).
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest

from narrative_radar.collectors.author import AuthorHasher
from narrative_radar.collectors.guard import CollectionBlocked
from narrative_radar.collectors.http import PoliteClient
from narrative_radar.collectors.rate_limit import MinIntervalLimiter
from narrative_radar.collectors.reddit import Query, RedditArcticCollector, plan_queries
from narrative_radar.core.clock import FixedClock
from narrative_radar.schemas.enums import ContentAccessStatus, IngestMode

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)


def _ts(dt: datetime) -> int:
    return int(dt.timestamp())


POST = {
    "id": "abc1",
    "author": "alice",
    "title": "Example NVDA earnings thread",
    "selftext": "Example body about guidance",
    "created_utc": _ts(NOW - timedelta(minutes=3)),
    "score": 10,
    "num_comments": 4,
    "url": "https://www.reddit.com/r/NVDA_Stock/comments/abc1/",
    "is_self": True,
    "subreddit": "NVDA_Stock",
}
COMMENT = {
    "id": "c9",
    "author": "bob",
    "body": "Example comment: HBM supply is the bottleneck for $NVDA",
    "created_utc": _ts(NOW - timedelta(days=30)),
    "score": 3,
    "link_id": "t3_abc1",
    "parent_id": "t3_abc1",
    "subreddit": "wallstreetbets",
}


def make(items, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if seen is not None:
            seen.append(parse_qs(request.url.query.decode()))
        return httpx.Response(200, json={"data": items})

    client = PoliteClient(
        "NarrativeRadar/test", limiter=MinIntervalLimiter(0), transport=httpx.MockTransport(handler)
    )
    return RedditArcticCollector(client, AuthorHasher("s" * 32), FixedClock(NOW), ["NVDA", "HBM"])


def test_plan_reads_full_subreddit_and_keyword_subreddits_per_term():
    qs = plan_queries(["NVDA"], full=["NVDA_Stock"], keyword=["stocks"])
    assert [(q.kind, q.subreddit, q.term) for q in qs] == [
        ("posts", "NVDA_Stock", None),
        ("comments", "NVDA_Stock", None),
        ("posts", "stocks", "NVDA"),
        ("comments", "stocks", "NVDA"),
    ]


def test_post_and_comment_map_to_unverified_documents():
    seen: list = []
    c = make([POST], seen)
    [post] = c.fetch(Query("posts", "NVDA_Stock", None), NOW - timedelta(days=1), NOW).documents
    assert post.external_id == "t3_abc1" and post.thread_external_id == "t3_abc1"
    assert post.content_access_status == ContentAccessStatus.UNVERIFIED
    assert post.ingest_mode == IngestMode.LIVE
    assert post.source_url == "https://www.reddit.com/r/NVDA_Stock/comments/abc1/"
    assert seen[0]["sort"] == ["asc"] and "title" not in seen[0]

    seen.clear()
    c = make([COMMENT], seen)
    [cm] = c.fetch(
        Query("comments", "wallstreetbets", "HBM"), NOW - timedelta(days=60), NOW
    ).documents
    assert (cm.external_id, cm.parent_external_id) == ("t1_c9", "t3_abc1")
    assert cm.source_url == "https://www.reddit.com/r/wallstreetbets/comments/abc1/_/c9/"
    assert cm.ingest_mode == IngestMode.BACKFILL
    assert seen[0]["body"] == ["HBM"]


def test_keyword_results_are_rechecked_and_removed_items_skipped():
    noise = {**COMMENT, "id": "c10", "body": "me da envidia"}
    removed = {**COMMENT, "id": "c11", "body": "[removed]"}
    c = make([noise, removed, COMMENT])
    docs = c.fetch(
        Query("comments", "wallstreetbets", "NVDA"), NOW - timedelta(days=60), NOW
    ).documents
    assert [d.external_id for d in docs] == ["t1_c9"]


def test_full_page_continues_from_newest_item(monkeypatch):
    monkeypatch.setattr("narrative_radar.collectors.reddit.PAGE_SIZE", 1)
    c = make([COMMENT])
    chunk = c.fetch(Query("comments", "NVDA_Stock", None), NOW - timedelta(days=60), NOW)
    assert chunk.next_after == datetime.fromtimestamp(COMMENT["created_utc"], tz=UTC)
    monkeypatch.undo()
    assert (
        make([COMMENT])
        .fetch(Query("comments", "NVDA_Stock", None), NOW - timedelta(days=60), NOW)
        .next_after
        is None
    )


def test_error_response_stops_collection():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, json={"data": None, "error": "Timeout"})

    client = PoliteClient(
        "NarrativeRadar/test", limiter=MinIntervalLimiter(0), transport=httpx.MockTransport(handler)
    )
    c = RedditArcticCollector(client, AuthorHasher("s" * 32), FixedClock(NOW), ["NVDA"])
    with pytest.raises(CollectionBlocked):
        c.fetch(Query("posts", "NVDA_Stock", None), NOW - timedelta(days=1), NOW)

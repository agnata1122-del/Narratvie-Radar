"""형식 검증용 예시 응답.

공개된 Algolia·Firebase API 형식을 따라 직접 작성했다 (DECISIONS D0 예외).
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest

from narrative_radar.collectors.author import AuthorHasher
from narrative_radar.collectors.guard import CollectionBlocked, TripKind
from narrative_radar.collectors.hackernews import HackerNewsCollector, minimal_terms
from narrative_radar.collectors.http import PoliteClient
from narrative_radar.collectors.rate_limit import MinIntervalLimiter
from narrative_radar.core.clock import FixedClock
from narrative_radar.schemas.enums import IngestMode

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)


def _ts(dt: datetime) -> int:
    return int(dt.timestamp())


STORY = {
    "objectID": "41000001",
    "_tags": ["story", "author_alice", "story_41000001"],
    "created_at_i": _ts(NOW - timedelta(minutes=5)),
    "title": "Example story mentioning Nvidia",
    "url": "https://example.com/article",
    "story_text": None,
    "author": "alice",
    "points": 12,
    "num_comments": 4,
}
COMMENT = {
    "objectID": "41000002",
    "_tags": ["comment", "author_bob", "story_41000001"],
    "created_at_i": _ts(NOW - timedelta(hours=2)),
    "story_title": "Example story mentioning Nvidia",
    "comment_text": '<p>Example comment about <i>NVDA</i> supply.<p>Second line <a href="https://example.org">link</a>',
    "story_id": 41000001,
    "parent_id": 41000001,
    "author": "bob",
}
AUTHOR_ONLY_MATCH = {
    "objectID": "41000003",
    "_tags": ["comment", "author_nvidia_fan"],
    "created_at_i": _ts(NOW - timedelta(minutes=1)),
    "story_title": "Unrelated",
    "comment_text": "<p>nothing relevant here</p>",
    "story_id": 1,
    "parent_id": 1,
    "author": "nvidia_fan",
}


def make(handler, clock=None):
    clock = clock or FixedClock(NOW)
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return handler(request)

    client = PoliteClient(
        "NarrativeRadar/test",
        limiter=MinIntervalLimiter(0),
        transport=httpx.MockTransport(recording),
    )
    collector = HackerNewsCollector(client, AuthorHasher("s" * 32), clock, terms=["nvidia", "NVDA"])
    return collector, requests


def search_handler(hits_by_term):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "hn.algolia.com"
        q = parse_qs(request.url.query.decode())
        return httpx.Response(
            200, json={"hits": hits_by_term.get(q["query"][0], []), "nbPages": 1, "page": 0}
        )

    return handler


def test_poll_maps_stories_and_comments_and_dedupes_across_terms():
    collector, requests = make(
        search_handler({"nvidia": [STORY, COMMENT, AUTHOR_ONLY_MATCH], "NVDA": [COMMENT]})
    )
    result = collector.poll(since=None)
    docs = {d.external_id: d for d in result.documents}
    assert set(docs) == {"41000001", "41000002"}  # 작성자 이름만 걸린 결과는 제외

    story = docs["41000001"]
    assert story.thread_external_id == "41000001" and story.parent_external_id is None
    assert story.metrics.upvote_count == 12 and story.metrics.comment_count == 4
    assert story.source_url == "https://news.ycombinator.com/item?id=41000001"
    assert "https://example.com/article" in story.body_text
    assert story.ingest_mode == IngestMode.LIVE

    comment = docs["41000002"]
    assert comment.parent_external_id == "41000001" and comment.thread_external_id == "41000001"
    assert comment.body_text == (
        "Example comment about NVDA supply.\nSecond line link (https://example.org)"
    )
    assert comment.metrics is None
    # 게시 후 10분 넘게 지나서 본 글은 backfill
    assert comment.ingest_mode == IngestMode.BACKFILL

    assert story.author_hash is not None and len(story.author_hash) == 64
    assert "alice" not in story.model_dump_json()
    assert result.newest_published_at == story.published_at
    assert result.queries == 2


def test_poll_requests_overlap_with_previous_poll():
    collector, requests = make(search_handler({}))
    since = NOW - timedelta(minutes=2)
    collector.poll(since=since)
    searches = [
        r for r in requests if r.url.host == "hn.algolia.com" and r.url.path != "/robots.txt"
    ]
    q = parse_qs(searches[0].url.query.decode())
    assert q["numericFilters"] == [f"created_at_i>{_ts(since - timedelta(minutes=10))}"]
    assert q["tags"] == ["(story,comment)"]


def test_unexpected_response_shape_stops_collection():
    collector, _ = make(lambda r: httpx.Response(200, json={"results": []}))
    with pytest.raises(CollectionBlocked):
        collector.poll(since=None)
    assert collector.client.guard.tripped_kind == TripKind.ERROR
    assert "parse failed" in collector.client.guard.tripped_reason


def test_non_json_response_stops_collection():
    collector, _ = make(lambda r: httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(CollectionBlocked):
        collector.poll(since=None)
    assert collector.client.guard.tripped


@pytest.mark.parametrize(
    "item",
    [None, {"id": 41000001, "deleted": True}, {"id": 41000001, "dead": True, "type": "story"}],
)
def test_revisit_detects_deleted_or_dead_items(item):
    # Firebase는 없는 항목에 JSON null을 돌려준다
    payload = b"null" if item is None else None
    collector, _ = make(
        lambda r: (
            httpx.Response(200, content=payload) if payload else httpx.Response(200, json=item)
        )
    )
    assert collector.revisit("41000001").deleted


def test_revisit_reads_story_metrics_but_not_comment_reply_counts():
    story = {"id": 41000001, "type": "story", "score": 30, "descendants": 9, "kids": [1, 2]}
    collector, requests = make(lambda r: httpx.Response(200, json=story))
    revisit = collector.revisit("41000001")
    assert not revisit.deleted
    assert (revisit.metrics.upvote_count, revisit.metrics.comment_count) == (30, 9)
    assert requests[-1].url.host == "hacker-news.firebaseio.com"

    comment = {"id": 41000002, "type": "comment", "kids": [3]}
    collector, _ = make(lambda r: httpx.Response(200, json=comment))
    revisit = collector.revisit("41000002")
    assert (revisit.metrics.upvote_count, revisit.metrics.comment_count) == (None, None)


def test_terms_contained_in_other_terms_are_dropped():
    assert minimal_terms(["NVIDIA", "NVDA", "NVIDIA Corporation", "nvidia", " "]) == [
        "NVIDIA",
        "NVDA",
    ]


def test_backfill_chunk_walks_back_from_oldest_hit_when_page_is_full(monkeypatch):
    monkeypatch.setattr("narrative_radar.collectors.hackernews.BACKFILL_HITS", 2)
    seen: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(parse_qs(request.url.query.decode()))
        return httpx.Response(200, json={"hits": [STORY, COMMENT], "nbPages": 1})

    collector, _ = make(handler)
    start, end = NOW - timedelta(days=365), NOW
    chunk = collector.backfill_chunk("nvidia", start, end)
    assert [d.external_id for d in chunk.documents] == ["41000001", "41000002"]
    assert all(d.ingest_mode == IngestMode.BACKFILL for d in chunk.documents[1:])
    # 다음 질의는 가장 오래된 글(COMMENT) 앞에서 다시 시작한다
    assert chunk.next_end == datetime.fromtimestamp(COMMENT["created_at_i"], tz=UTC)
    q = seen[0]
    assert q["numericFilters"] == [f"created_at_i>{_ts(start)},created_at_i<{_ts(end)}"]
    assert q["typoTolerance"] == ["false"] and q["queryType"] == ["prefixNone"]


def test_backfill_chunk_ends_when_page_is_not_full():
    collector, _ = make(lambda r: httpx.Response(200, json={"hits": [STORY], "nbPages": 1}))
    chunk = collector.backfill_chunk("nvidia", NOW - timedelta(days=30), NOW)
    assert chunk.next_end is None

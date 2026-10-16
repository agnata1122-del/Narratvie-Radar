"""형식 검증용 예시 이벤트.

공개된 Jetstream·AppView 형식을 따라 직접 작성했다 (DECISIONS D0 예외).
"""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.http11 import Response

from narrative_radar.collectors.author import AuthorHasher
from narrative_radar.collectors.bluesky import (
    BlueskyMetrics,
    DeleteAuthor,
    DeletePost,
    EnvelopeError,
    JetstreamHandler,
    JetstreamStream,
    SavePost,
    jetstream_url,
)
from narrative_radar.collectors.guard import BlockGuard, CollectionBlocked, TripKind
from narrative_radar.collectors.http import PoliteClient
from narrative_radar.collectors.rate_limit import MinIntervalLimiter
from narrative_radar.core.clock import FixedClock
from narrative_radar.schemas.enums import IngestMode

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
DID = "did:plc:exampleuser000000000000"


def _us(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000)


def post_event(text, rkey="3kexample01", at=NOW - timedelta(seconds=2), reply=None, op="create"):
    record = {"$type": "app.bsky.feed.post", "text": text, "createdAt": "2020-01-01T00:00:00Z"}
    if reply:
        record["reply"] = reply
    return {
        "did": DID,
        "time_us": _us(at),
        "kind": "commit",
        "commit": {
            "rev": "3kexamplerev",
            "operation": op,
            "collection": "app.bsky.feed.post",
            "rkey": rkey,
            "record": record,
            "cid": "bafyexample",
        },
    }


def handler(clock=None) -> JetstreamHandler:
    return JetstreamHandler(
        AuthorHasher("s" * 32), clock or FixedClock(NOW), terms=["NVIDIA", "NVDA", "엔비디아"]
    )


def test_matching_post_becomes_document_and_unrelated_post_is_skipped():
    h = handler()
    [action] = h.handle(post_event("Example post: $NVDA guidance next week"))
    assert isinstance(action, SavePost)
    doc = action.document
    assert doc.external_id == f"at://{DID}/app.bsky.feed.post/3kexample01"
    assert doc.source_url == f"https://bsky.app/profile/{DID}/post/3kexample01"
    assert doc.thread_external_id == doc.external_id
    # 사용자가 적은 createdAt(2020년)이 아니라 서버 수신 시각을 쓴다
    assert doc.published_at == NOW - timedelta(seconds=2)
    assert doc.ingest_mode == IngestMode.LIVE
    # 글 주소와 링크에는 계정 ID가 들어가지만(DATA_POLICY 8), 작성자 필드와 본문에는 없다
    assert doc.author_hash != DID and len(doc.author_hash) == 64
    fields_with_did = {k for k, v in doc.model_dump().items() if isinstance(v, str) and DID in v}
    assert fields_with_did == {"external_id", "thread_external_id", "source_url"}

    assert h.handle(post_event("talking about something else", rkey="3kother")) == []
    assert h.handle(post_event("엔비디아 예시 글", rkey="3kkorean"))[0].document.body_text
    assert (h.stats.posts_seen, h.stats.posts_matched) == (3, 2)
    assert h.last_time_us == _us(NOW - timedelta(seconds=2))


def test_replies_keep_parent_and_root():
    parent = f"at://{DID}/app.bsky.feed.post/3kparent"
    root = f"at://{DID}/app.bsky.feed.post/3kroot"
    reply = {"parent": {"uri": parent, "cid": "x"}, "root": {"uri": root, "cid": "y"}}
    [action] = handler().handle(post_event("nvidia reply", reply=reply))
    assert action.document.parent_external_id == parent
    assert action.document.thread_external_id == root


def test_late_events_after_resume_are_backfill():
    [action] = handler().handle(post_event("nvidia", at=NOW - timedelta(hours=3)))
    assert action.document.ingest_mode == IngestMode.BACKFILL


def test_delete_and_account_events():
    h = handler()
    delete = {
        "did": DID,
        "time_us": _us(NOW),
        "kind": "commit",
        "commit": {"operation": "delete", "collection": "app.bsky.feed.post", "rkey": "3kgone"},
    }
    assert h.handle(delete) == [DeletePost(f"at://{DID}/app.bsky.feed.post/3kgone")]

    account = {
        "did": DID,
        "time_us": _us(NOW),
        "kind": "account",
        "account": {"active": False, "status": "deleted", "did": DID},
    }
    [action] = h.handle(account)
    assert isinstance(action, DeleteAuthor) and action.reason == "deleted"
    assert len(action.author_hash) == 64

    reactivated = {**account, "account": {"active": True, "did": DID}}
    assert h.handle(reactivated) == []
    assert h.handle({"did": DID, "time_us": _us(NOW), "kind": "identity", "identity": {}}) == []


def test_malformed_user_record_is_skipped_but_bad_envelope_stops():
    h = handler()
    event = post_event("nvidia")
    event["commit"]["record"] = {"text": 123}
    assert h.handle(event) == []
    assert h.stats.malformed_records == 1

    with pytest.raises(EnvelopeError):
        h.handle({"kind": "commit"})
    with pytest.raises(EnvelopeError):
        h.handle(["not", "an", "object"])


class FakeWebSocket:
    def __init__(self, messages, end_with):
        self.messages = list(messages)
        self.end_with = end_with

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def recv(self):
        if self.messages:
            return self.messages.pop(0)
        raise self.end_with


def fake_connect(ws, seen):
    def connect(url, **kwargs):
        seen.append((url, kwargs))
        return ws

    return connect


def test_stream_yields_events_then_stops_when_connection_drops():
    seen = []
    ws = FakeWebSocket([json.dumps(post_event("nvidia"))], ConnectionClosedError(None, None))
    guard = BlockGuard()
    stream = JetstreamStream("NarrativeRadar/test", guard, connect=fake_connect(ws, seen))
    events = stream.events(cursor_time_us=123)
    assert next(events)["kind"] == "commit"
    with pytest.raises(CollectionBlocked):
        next(events)
    assert guard.tripped_kind == TripKind.ERROR
    url, kwargs = seen[0]
    q = parse_qs(urlsplit(url).query)
    assert q == {"wantedCollections": ["app.bsky.feed.post"], "cursor": ["123"]}
    assert kwargs["user_agent_header"] == "NarrativeRadar/test"
    # 멈춘 뒤에는 다시 연결하지 않는다
    with pytest.raises(CollectionBlocked):
        next(stream.events(cursor_time_us=None))
    assert len(seen) == 1


@pytest.mark.parametrize(("status", "kind"), [(429, TripKind.BLOCKED), (502, TripKind.ERROR)])
def test_rejected_handshake_stops(status, kind):
    def connect(url, **kwargs):
        raise InvalidStatus(Response(status, "x", None))

    guard = BlockGuard()
    with pytest.raises(CollectionBlocked):
        next(JetstreamStream("NarrativeRadar/test", guard, connect=connect).events(None))
    assert guard.tripped_kind == kind


def test_non_json_message_stops():
    ws = FakeWebSocket(["not json"], ConnectionClosedError(None, None))
    guard = BlockGuard()
    with pytest.raises(CollectionBlocked):
        next(
            JetstreamStream("NarrativeRadar/test", guard, connect=fake_connect(ws, [])).events(None)
        )
    assert "non-JSON" in guard.tripped_reason


def test_browser_user_agent_is_refused():
    with pytest.raises(ValueError):
        JetstreamStream("Mozilla/5.0", BlockGuard())


def test_jetstream_url_without_cursor():
    assert jetstream_url("wss://example.test/subscribe", None) == (
        "wss://example.test/subscribe?wantedCollections=app.bsky.feed.post"
    )


def test_metrics_revisit_reads_counts_and_treats_missing_as_deleted():
    kept = f"at://{DID}/app.bsky.feed.post/3kkept"
    gone = f"at://{DID}/app.bsky.feed.post/3kgone"

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        assert parse_qs(request.url.query.decode())["uris"] == [kept, gone]
        return httpx.Response(
            200,
            json={
                "posts": [
                    {
                        "uri": kept,
                        "likeCount": 7,
                        "replyCount": 2,
                        "repostCount": 3,
                        "quoteCount": 1,
                    }
                ]
            },
        )

    client = PoliteClient(
        "NarrativeRadar/test", limiter=MinIntervalLimiter(0), transport=httpx.MockTransport(handle)
    )
    revisits = {
        r.external_id: r for r in BlueskyMetrics(client, FixedClock(NOW)).revisit_many([kept, gone])
    }
    assert revisits[gone].deleted
    m = revisits[kept].metrics
    assert (m.upvote_count, m.comment_count, m.share_count) == (7, 2, 4)

"""Bluesky 수집기 (공식 공개 스트림, DATA_POLICY 1장).

- 새 글: Jetstream 웹소켓에서 게시물 이벤트를 받아 관심 키워드가 들어간 글만 남긴다.
  Jetstream은 전체 공개 게시물을 보내므로 걸러내는 일은 우리 쪽에서 한다.
- 삭제: 게시물 삭제 이벤트, 계정 비활성화·삭제 이벤트가 오면 원문을 지운다
  (Bluesky 개발자 가이드라인, DATA_POLICY 12).
- 지표: 공개 AppView의 getPosts로 좋아요·답글·리포스트 수를 다시 확인한다.
- 중단: 연결이 거부되거나 끊기면 다시 붙지 않고 멈춘다 (DATA_POLICY 5). 재개할 때는 마지막
  커서부터 이어 받으며, 늦게 받은 글은 backfill로 표시한다.
- 이벤트 봉투(envelope) 구조가 예상과 다르면 멈춘다. 개별 사용자가 만든 레코드의 필드가
  이상한 것은 흔하므로 그 글만 건너뛰고 센다.
"""

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from urllib.parse import urlencode

from narrative_radar.collectors.author import AuthorHasher
from narrative_radar.collectors.base import Revisit
from narrative_radar.collectors.guard import BlockGuard, CollectionBlocked, TripKind
from narrative_radar.collectors.http import PoliteClient
from narrative_radar.core.clock import Clock
from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas.document import DocumentIn, MetricsIn
from narrative_radar.schemas.enums import ContentAccessStatus, IngestMode

SOURCE_ADAPTER_ID = "bluesky_jetstream"
PARSER_VERSION = "bluesky.v1"
POST_COLLECTION = "app.bsky.feed.post"
DEFAULT_JETSTREAM = "wss://jetstream2.us-east.bsky.network/subscribe"
GET_POSTS_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts"
GET_POSTS_MAX_URIS = 25

# 이보다 늦게 받은 글은 실시간으로 본 것이 아니므로 backfill로 표시한다 (DECISIONS D2).
LATE_THRESHOLD = timedelta(minutes=10)


def post_uri(did: str, rkey: str) -> str:
    return f"at://{did}/{POST_COLLECTION}/{rkey}"


def post_url(did: str, rkey: str) -> str:
    return f"https://bsky.app/profile/{did}/post/{rkey}"


# --- 이벤트 처리 (네트워크와 분리) ------------------------------------------------------------


@dataclass(frozen=True)
class SavePost:
    document: DocumentIn


@dataclass(frozen=True)
class DeletePost:
    external_id: str


@dataclass(frozen=True)
class DeleteAuthor:
    author_hash: str
    reason: str


Action = SavePost | DeletePost | DeleteAuthor


class EnvelopeError(ValueError):
    """Jetstream 이벤트 봉투가 예상과 다르다. 수집을 멈춰야 한다."""


@dataclass
class HandlerStats:
    events: int = 0
    posts_seen: int = 0
    posts_matched: int = 0
    malformed_records: int = 0
    deletes: int = 0
    account_removals: int = 0


@dataclass
class JetstreamHandler:
    hasher: AuthorHasher
    clock: Clock
    terms: Sequence[str]
    stats: HandlerStats = field(default_factory=HandlerStats)
    last_time_us: int | None = None

    def __post_init__(self) -> None:
        self._terms = [normalize_text(t) for t in self.terms if t.strip()]
        if not self._terms:
            raise ValueError("at least one search term is required")

    def handle(self, event: Any) -> list[Action]:
        if not isinstance(event, dict):
            raise EnvelopeError(f"event is {type(event).__name__}, not an object")
        kind = event.get("kind")
        did = event.get("did")
        time_us = event.get("time_us")
        if not isinstance(did, str) or not isinstance(time_us, int) or not isinstance(kind, str):
            raise EnvelopeError(f"missing did/time_us/kind in event: {sorted(event)}")
        self.stats.events += 1
        self.last_time_us = time_us

        if kind == "commit":
            return self._commit(did, time_us, event.get("commit"))
        if kind == "account":
            return self._account(did, event.get("account"))
        return []  # identity 등은 쓰지 않는다

    def _commit(self, did: str, time_us: int, commit: Any) -> list[Action]:
        if not isinstance(commit, dict):
            raise EnvelopeError("commit event without commit object")
        if commit.get("collection") != POST_COLLECTION:
            return []
        operation, rkey = commit.get("operation"), commit.get("rkey")
        if not isinstance(operation, str) or not isinstance(rkey, str):
            raise EnvelopeError("commit without operation/rkey")
        if operation == "delete":
            self.stats.deletes += 1
            return [DeletePost(post_uri(did, rkey))]
        if operation not in ("create", "update"):
            return []

        self.stats.posts_seen += 1
        record = commit.get("record")
        text = record.get("text") if isinstance(record, dict) else None
        if not isinstance(text, str):
            self.stats.malformed_records += 1
            return []
        if not self._matches(text):
            return []

        self.stats.posts_matched += 1
        published_at = datetime.fromtimestamp(time_us / 1_000_000, tz=UTC)
        observed_at = self.clock.now()
        uri = post_uri(did, rkey)
        parent, root = _reply_refs(record)
        return [
            SavePost(
                DocumentIn(
                    source_adapter_id=SOURCE_ADAPTER_ID,
                    external_id=uri,
                    parent_external_id=parent,
                    thread_external_id=root or uri,
                    source_url=post_url(did, rkey),
                    title="",
                    body_text=text,
                    author_hash=self.hasher.hash("bluesky", did),
                    # 사용자가 적는 createdAt 대신, 서버가 이벤트를 받은 시각을 쓴다
                    published_at=published_at,
                    observed_at=observed_at,
                    content_access_status=ContentAccessStatus.PERMITTED,
                    ingest_mode=(
                        IngestMode.BACKFILL
                        if observed_at - published_at > LATE_THRESHOLD
                        else IngestMode.LIVE
                    ),
                )
            )
        ]

    def _account(self, did: str, account: Any) -> list[Action]:
        if not isinstance(account, dict):
            raise EnvelopeError("account event without account object")
        if account.get("active") is False:
            self.stats.account_removals += 1
            author_hash = self.hasher.hash("bluesky", did)
            if author_hash:
                return [DeleteAuthor(author_hash, str(account.get("status") or "inactive"))]
        return []

    def _matches(self, text: str) -> bool:
        normalized = normalize_text(text)
        return any(term in normalized for term in self._terms)


def _reply_refs(record: dict[str, Any]) -> tuple[str | None, str | None]:
    reply = record.get("reply")
    if not isinstance(reply, dict):
        return None, None
    parent = reply.get("parent", {}).get("uri") if isinstance(reply.get("parent"), dict) else None
    root = reply.get("root", {}).get("uri") if isinstance(reply.get("root"), dict) else None
    return (parent if isinstance(parent, str) else None, root if isinstance(root, str) else None)


# --- 스트림 연결 --------------------------------------------------------------------------


Connector = Callable[..., Any]


def jetstream_url(base: str, cursor_time_us: int | None) -> str:
    params: list[tuple[str, str]] = [("wantedCollections", POST_COLLECTION)]
    if cursor_time_us is not None:
        params.append(("cursor", str(cursor_time_us)))
    return f"{base}?{urlencode(params)}"


class JetstreamStream:
    """웹소켓 연결 하나를 유지하며 이벤트를 넘긴다. 문제가 생기면 다시 붙지 않고 멈춘다."""

    def __init__(
        self,
        user_agent: str,
        guard: BlockGuard,
        base_url: str = DEFAULT_JETSTREAM,
        connect: Connector | None = None,
    ) -> None:
        if "mozilla" in user_agent.lower():
            raise ValueError("user agent must identify this project")
        self.user_agent = user_agent
        self.guard = guard
        self.base_url = base_url
        self._connect = connect

    def events(self, cursor_time_us: int | None) -> Iterator[Any]:
        import json

        from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

        connect = self._connect
        if connect is None:
            from websockets.sync.client import connect as ws_connect

            connect = ws_connect

        self.guard.check()
        url = jetstream_url(self.base_url, cursor_time_us)
        try:
            with connect(url, user_agent_header=self.user_agent, open_timeout=20) as ws:
                for message in _iter_messages(ws):
                    try:
                        yield json.loads(message)
                    except ValueError as e:
                        self._stop(TripKind.ERROR, f"non-JSON message from jetstream: {e}")
        except InvalidStatus as e:
            status = e.response.status_code
            kind = TripKind.BLOCKED if status in (401, 403, 429) else TripKind.ERROR
            self._stop(kind, f"jetstream handshake rejected: HTTP {status}")
        except ConnectionClosed as e:
            self._stop(TripKind.ERROR, f"jetstream connection closed: {e}")
        except (OSError, TimeoutError, WebSocketException) as e:
            self._stop(TripKind.ERROR, f"jetstream connection failed: {type(e).__name__}: {e}")
        # 서버가 정상 종료해도 실시간 수집이 끊긴 것이므로 멈춘다.
        self._stop(TripKind.ERROR, "jetstream stream ended")

    def _stop(self, kind: TripKind, reason: str) -> NoReturn:
        self.guard.trip(kind, reason)
        raise CollectionBlocked(reason)


def _iter_messages(ws: Any) -> Iterable[str | bytes]:
    while True:
        yield ws.recv()


# --- 지표 재방문 --------------------------------------------------------------------------


class BlueskyMetrics:
    """공개 AppView에서 게시물 지표를 확인한다. 응답에 없는 게시물은 지워진 것으로 본다."""

    def __init__(self, client: PoliteClient, clock: Clock) -> None:
        self.client = client
        self.clock = clock

    def revisit_many(self, uris: Sequence[str]) -> list[Revisit]:
        results: list[Revisit] = []
        for i in range(0, len(uris), GET_POSTS_MAX_URIS):
            batch = list(uris[i : i + GET_POSTS_MAX_URIS])
            response = self.client.get(f"{GET_POSTS_URL}?{urlencode([('uris', u) for u in batch])}")
            observed_at = self.clock.now()
            try:
                posts = response.json()["posts"]
                by_uri = {p["uri"]: p for p in posts}
            except (ValueError, KeyError, TypeError) as e:
                self.client.guard.trip(TripKind.ERROR, f"parse failed: getPosts response: {e!r}")
                raise CollectionBlocked(str(e)) from e
            for uri in batch:
                post = by_uri.get(uri)
                if post is None:
                    results.append(Revisit(uri, observed_at, deleted=True))
                    continue
                shares = _int_or_none(post.get("repostCount"))
                quotes = _int_or_none(post.get("quoteCount"))
                results.append(
                    Revisit(
                        uri,
                        observed_at,
                        metrics=MetricsIn(
                            comment_count=_int_or_none(post.get("replyCount")),
                            upvote_count=_int_or_none(post.get("likeCount")),
                            share_count=None if shares is None else shares + (quotes or 0),
                        ),
                    )
                )
        return results


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None

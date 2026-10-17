"""Reddit 수집기 (Arctic Shift 보관본, DECISIONS D31).

- Reddit 글·댓글을 다시 모아 둔 Arctic Shift 공개 API에서 받는다. Reddit의 이용 허락은 확인되지
  않았으므로 원문은 `unverified`로 저장한다(내부 분석만, 화면에는 발췌·링크만).
- 투자 서브레딧 하나(r/NVDA_Stock)는 전부 받고, 큰 서브레딧은 검색어가 들어간 것만 남긴다.
  댓글은 서버에서 본문(body)으로 찾고, 게시물은 다 받아 거른다(제목 검색은 시간 초과가 잦다).
- 오래된 것부터(sort=asc) 100건씩 받고, 마지막 시각부터 이어 받는다.
- 보관본은 늦게 채워지므로 실행마다 앞쪽을 겹쳐 받는다. 중복은 저장 단계가 걸러낸다.
- 이미 지워진 글([deleted]/[removed])은 받지 않는다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn

from narrative_radar.collectors.author import AuthorHasher
from narrative_radar.collectors.guard import CollectionBlocked, TripKind
from narrative_radar.collectors.http import PoliteClient
from narrative_radar.core.clock import Clock
from narrative_radar.normalization.text import normalize_text, term_pattern
from narrative_radar.schemas.document import DocumentIn, MetricsIn
from narrative_radar.schemas.enums import ContentAccessStatus, IngestMode

SOURCE_ADAPTER_ID = "reddit_arctic"
PARSER_VERSION = "reddit_arctic.v1"
API = "https://arctic-shift.photon-reddit.com/api/{kind}/search"
PAGE_SIZE = 100
# 요청 간격. 3초로는 15분쯤 뒤 429로 막혔다 (2026-10-17)
REDDIT_MIN_INTERVAL_SECONDS = 10.0

# 전부 받는 서브레딧과 검색어로만 받는 서브레딧
FULL_SUBREDDITS = ("NVDA_Stock",)
KEYWORD_SUBREDDITS = ("wallstreetbets", "stocks")

POST_FIELDS = "id,author,title,selftext,created_utc,score,num_comments,url,subreddit"
COMMENT_FIELDS = "id,author,body,created_utc,score,link_id,parent_id,subreddit"
REMOVED = frozenset({"[deleted]", "[removed]"})


@dataclass(frozen=True)
class Query:
    kind: str  # posts | comments
    subreddit: str
    term: str | None  # 서버에 묻는 검색어. None이면 서브레딧 전체를 받는다
    keep_if_any: tuple[str, ...] = ()  # 전체를 받되 이 중 하나가 들어간 것만 남긴다

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.subreddit}:{normalize_text(self.term) if self.term else '*'}"


@dataclass(frozen=True)
class Chunk:
    documents: list[DocumentIn]
    next_after: datetime | None  # 다음 요청의 시작 시각. None이면 before까지 다 받았다
    newest: datetime | None


def plan_queries(
    terms: Sequence[str],
    full: Sequence[str] = FULL_SUBREDDITS,
    keyword: Sequence[str] = KEYWORD_SUBREDDITS,
) -> list[Query]:
    out = [Query(kind, sub, None) for sub in full for kind in ("posts", "comments")]
    for sub in keyword:
        # 큰 서브레딧 제목 검색은 시간 초과가 잦다. 게시물은 하루 수백 건이라 다 받고 거른다
        out.append(Query("posts", sub, None, tuple(terms)))
        out += [Query("comments", sub, t) for t in terms]
    return out


def server_term(term: str) -> str:
    """여러 단어로 된 검색어는 서버에서 시간 초과가 잦아 가장 긴 단어 하나로 묻는다.
    전체 표현이 들어 있는지는 받은 뒤 단어 단위로 다시 확인한다."""
    return max(term.split(), key=len) if " " in term.strip() else term


class RedditArcticCollector:
    source_adapter_id = SOURCE_ADAPTER_ID
    parser_version = PARSER_VERSION

    def __init__(
        self,
        client: PoliteClient,
        hasher: AuthorHasher,
        clock: Clock,
        terms: Sequence[str],
        late_threshold: timedelta = timedelta(minutes=10),
    ) -> None:
        self.client = client
        self.hasher = hasher
        self.clock = clock
        self.terms = list(terms)
        self.late_threshold = late_threshold

    def queries(self) -> list[Query]:
        return plan_queries(self.terms)

    def fetch(self, query: Query, after: datetime, before: datetime) -> Chunk:
        params = {
            "subreddit": query.subreddit,
            "after": str(int(after.timestamp())),
            "before": str(int(before.timestamp())),
            "limit": str(PAGE_SIZE),
            "sort": "asc",
            "fields": POST_FIELDS if query.kind == "posts" else COMMENT_FIELDS,
        }
        if query.term:
            params["title" if query.kind == "posts" else "body"] = server_term(query.term)
        response = self.client.get(API.format(kind=query.kind), params=params)
        try:
            body = response.json()
        except ValueError as e:
            self._parse_failed(f"non-JSON response: {e}")
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            self._parse_failed(f"unexpected response: {str(body)[:200]}")
        items: list[Any] = body["data"]

        observed_at = self.clock.now()
        docs: list[DocumentIn] = []
        newest: datetime | None = None
        for item in items:
            doc = self._to_document(query, item, observed_at)
            published = _created(item)
            newest = published if newest is None else max(newest, published)
            if doc is not None:
                docs.append(doc)
        if len(items) < PAGE_SIZE or newest is None:
            return Chunk(docs, None, newest)
        # 같은 초에 한 쪽이 다 차면 1초 밀어 무한 반복을 막는다
        next_after = max(newest, after + timedelta(seconds=1)) if newest <= after else newest
        return Chunk(docs, next_after, newest)

    # --- 내부 ---------------------------------------------------------------------------

    def _to_document(self, query: Query, item: Any, observed_at: datetime) -> DocumentIn | None:
        try:
            rid = str(item["id"])
            sub = str(item.get("subreddit") or query.subreddit)
            published_at = _created(item)
            author = str(item.get("author") or "")
            if query.kind == "posts":
                title = str(item.get("title") or "")
                text = str(item.get("selftext") or "")
                if text in REMOVED:
                    text = ""
                written = text
                link = str(item.get("url") or "")
                if link and f"/comments/{rid}" not in link:  # 링크 게시물이면 그 주소를 붙인다
                    text = "\n".join(p for p in (text, link) if p)
                external_id, parent, thread = f"t3_{rid}", None, f"t3_{rid}"
                url = f"https://www.reddit.com/r/{sub}/comments/{rid}/"
                metrics = MetricsIn(
                    upvote_count=_score(item), comment_count=item.get("num_comments")
                )
                if title in REMOVED:
                    return None
            else:
                title = ""
                text = str(item.get("body") or "")
                if text in REMOVED:
                    return None
                written = text
                link_id = str(item["link_id"])
                external_id, parent, thread = f"t1_{rid}", str(item["parent_id"]), link_id
                url = f"https://www.reddit.com/r/{sub}/comments/{link_id.removeprefix('t3_')}/_/{rid}/"
                metrics = MetricsIn(upvote_count=_score(item))
        except (KeyError, TypeError, ValueError) as e:
            self._parse_failed(f"unexpected item shape: {e!r}")

        wanted = (query.term,) if query.term else query.keep_if_any
        if wanted:
            # 링크 주소(예: /r/NVDA_Stock/…)가 아니라 쓴 글에서만 찾는다
            normalized = normalize_text(f"{title}\n{written}")
            if not any(term_pattern(t).search(normalized) for t in wanted):
                return None  # 서버 검색은 넓게 잡는다. 단어 단위로 다시 확인한다

        return DocumentIn(
            source_adapter_id=SOURCE_ADAPTER_ID,
            external_id=external_id,
            parent_external_id=parent,
            thread_external_id=thread,
            source_url=url,
            title=title,
            body_text=text or None,
            author_hash=self.hasher.hash("reddit", author) if author not in REMOVED else None,
            published_at=published_at,
            observed_at=observed_at,
            content_access_status=ContentAccessStatus.UNVERIFIED,
            ingest_mode=(
                IngestMode.BACKFILL
                if observed_at - published_at > self.late_threshold
                else IngestMode.LIVE
            ),
            metrics=metrics,
        )

    def _parse_failed(self, reason: str) -> NoReturn:
        self.client.guard.trip(TripKind.ERROR, f"parse failed: {reason}")
        raise CollectionBlocked(reason)


def _score(item: Any) -> int | None:
    """Reddit 점수는 추천−비추천이라 음수가 될 수 있다. 추천 수 칸에는 0 이상만 둔다."""
    score = item.get("score")
    return score if isinstance(score, int) and score >= 0 else None


def _created(item: Any) -> datetime:
    return datetime.fromtimestamp(int(item["created_utc"]), tz=UTC)

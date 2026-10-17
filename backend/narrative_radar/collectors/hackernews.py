"""Hacker News 수집기 (공식 API, DATA_POLICY 1장).

- 새 글: Algolia HN 검색 API `search_by_date`로 관심 키워드가 들어간 글·댓글을 가져온다.
- 재방문: 공식 Firebase API로 점수·댓글 수와 삭제(`deleted`)·숨김(`dead`) 여부를 확인한다.
- 게시보다 기준 시간(기본 10분) 넘게 늦게 본 글은 backfill로 표시한다 (DECISIONS D2, D16).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn

from narrative_radar.collectors.author import AuthorHasher
from narrative_radar.collectors.base import PollResult, Revisit
from narrative_radar.collectors.guard import CollectionBlocked, TripKind
from narrative_radar.collectors.html_text import html_to_text
from narrative_radar.collectors.http import PoliteClient
from narrative_radar.core.clock import Clock
from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas.document import DocumentIn, MetricsIn
from narrative_radar.schemas.enums import ContentAccessStatus, IngestMode

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
PERMALINK = "https://news.ycombinator.com/item?id={id}"

SOURCE_ADAPTER_ID = "hackernews"
PARSER_VERSION = "hackernews.v1"

# 검색 색인이 늦게 반영되는 경우를 대비해 직전 폴링과 겹치게 요청한다. 중복은 저장 단계가 걸러낸다.
OVERLAP = timedelta(minutes=10)
MAX_PAGES_PER_QUERY = 5
# 과거분 백필: Algolia가 한 질의에 주는 최대 건수. 다 차면 가장 오래된 시각 앞에서 다시 묻는다.
BACKFILL_HITS = 1000


@dataclass(frozen=True)
class BackfillChunk:
    documents: list[DocumentIn]
    next_end: datetime | None  # 다음 질의의 끝 시각. None이면 이 검색어는 start까지 다 받았다


class HackerNewsCollector:
    source_adapter_id = SOURCE_ADAPTER_ID
    parser_version = PARSER_VERSION

    def __init__(
        self,
        client: PoliteClient,
        hasher: AuthorHasher,
        clock: Clock,
        terms: Sequence[str],
        late_threshold: timedelta = timedelta(minutes=10),
        first_lookback: timedelta = timedelta(hours=1),
        hits_per_page: int = 100,
    ) -> None:
        if not terms:
            raise ValueError("at least one search term is required")
        self.client = client
        self.hasher = hasher
        self.clock = clock
        self.terms = minimal_terms(terms)
        self.late_threshold = late_threshold
        self.first_lookback = first_lookback
        self.hits_per_page = hits_per_page

    def poll(self, since: datetime | None) -> PollResult:
        start = (since - OVERLAP) if since else (self.clock.now() - self.first_lookback)
        seen: dict[str, DocumentIn] = {}
        newest: datetime | None = since
        queries = 0
        for term in self.terms:
            for page in range(MAX_PAGES_PER_QUERY):
                body = self._get_json(
                    SEARCH_URL,
                    {
                        "query": term,
                        "tags": "(story,comment)",
                        "numericFilters": f"created_at_i>{int(start.timestamp())}",
                        "hitsPerPage": str(self.hits_per_page),
                        "page": str(page),
                    },
                )
                queries += 1
                hits = self._require(body, "hits", list)
                observed_at = self.clock.now()
                for hit in hits:
                    doc = self._to_document(hit, observed_at)
                    if doc is None or doc.external_id in seen:
                        continue
                    seen[doc.external_id] = doc
                    if newest is None or doc.published_at > newest:
                        newest = doc.published_at
                if page + 1 >= int(self._require(body, "nbPages", int)):
                    break
        return PollResult(list(seen.values()), newest, queries)

    def backfill_chunk(self, term: str, start: datetime, end: datetime) -> BackfillChunk:
        """start < 게시 시각 < end 범위에서 최근 글부터 최대 BACKFILL_HITS건.

        긴 기간을 넓게 찾으면 오타 허용·앞부분 일치로 엉뚱한 글이 많이 걸려 둘 다 끈다.
        """
        body = self._get_json(
            SEARCH_URL,
            {
                "query": term,
                "tags": "(story,comment)",
                "numericFilters": (
                    f"created_at_i>{int(start.timestamp())},created_at_i<{int(end.timestamp())}"
                ),
                "hitsPerPage": str(BACKFILL_HITS),
                "typoTolerance": "false",
                "queryType": "prefixNone",
            },
        )
        hits = self._require(body, "hits", list)
        observed_at = self.clock.now()
        docs: list[DocumentIn] = []
        oldest: int | None = None
        for hit in hits:
            created = hit.get("created_at_i")
            if isinstance(created, int):
                oldest = created if oldest is None else min(oldest, created)
            doc = self._to_document(hit, observed_at)
            if doc is not None:
                docs.append(doc)
        if len(hits) < BACKFILL_HITS or oldest is None:
            return BackfillChunk(docs, None)
        # 같은 초에 1000건이 몰려 있으면 1초 당겨 무한 반복을 막는다
        next_end = min(datetime.fromtimestamp(oldest, tz=UTC), end - timedelta(seconds=1))
        return BackfillChunk(docs, next_end)

    def revisit(self, external_id: str) -> Revisit:
        item = self._get_json(ITEM_URL.format(id=external_id), None, allow_null=True)
        observed_at = self.clock.now()
        if item is None or item.get("deleted") or item.get("dead"):
            return Revisit(external_id, observed_at, deleted=True)
        is_story = item.get("type") == "story"
        metrics = MetricsIn(
            upvote_count=item.get("score") if is_story else None,
            comment_count=item.get("descendants") if is_story else None,
        )
        return Revisit(external_id, observed_at, metrics=metrics)

    # --- 내부 ---------------------------------------------------------------------------

    def _to_document(self, hit: dict[str, Any], observed_at: datetime) -> DocumentIn | None:
        try:
            object_id = str(hit["objectID"])
            tags = hit.get("_tags") or []
            is_comment = "comment" in tags
            published_at = datetime.fromtimestamp(int(hit["created_at_i"]), tz=UTC)
            if is_comment:
                title = f"Re: {hit.get('story_title') or ''}".strip()
                body = html_to_text(hit.get("comment_text"))
                parent = _str_or_none(hit.get("parent_id"))
                thread = _str_or_none(hit.get("story_id"))
            else:
                title = hit.get("title") or ""
                body = "\n".join(
                    part for part in (html_to_text(hit.get("story_text")), hit.get("url")) if part
                )
                parent, thread = None, object_id
            author = hit.get("author") or ""
        except (KeyError, TypeError, ValueError) as e:
            self._parse_failed(f"unexpected search hit shape: {e!r}")

        if not self._mentions_term(title, body):
            return None  # 작성자 이름 등 본문 밖에서만 걸린 결과

        return DocumentIn(
            source_adapter_id=SOURCE_ADAPTER_ID,
            external_id=object_id,
            parent_external_id=parent,
            thread_external_id=thread,
            source_url=PERMALINK.format(id=object_id),
            title=title,
            body_text=body or None,
            author_hash=self.hasher.hash("hackernews", author),
            published_at=published_at,
            observed_at=observed_at,
            content_access_status=ContentAccessStatus.PERMITTED,
            ingest_mode=(
                IngestMode.BACKFILL
                if observed_at - published_at > self.late_threshold
                else IngestMode.LIVE
            ),
            metrics=None
            if is_comment
            else MetricsIn(upvote_count=hit.get("points"), comment_count=hit.get("num_comments")),
        )

    def _mentions_term(self, title: str, body: str) -> bool:
        text = normalize_text(f"{title}\n{body}")
        return any(normalize_text(t) in text for t in self.terms)

    def _get_json(self, url: str, params: dict[str, str] | None, allow_null: bool = False) -> Any:
        response = self.client.get(url, params=params)
        try:
            body = response.json()
        except ValueError as e:
            self._parse_failed(f"non-JSON response from {url}: {e}")
        if body is None and allow_null:
            return None
        if not isinstance(body, dict):
            self._parse_failed(f"expected JSON object from {url}, got {type(body).__name__}")
        return body

    def _require(self, body: dict[str, Any], key: str, kind: type) -> Any:
        value = body.get(key)
        if not isinstance(value, kind):
            self._parse_failed(f"missing or invalid '{key}' in search response")
        return value

    def _parse_failed(self, reason: str) -> NoReturn:
        self.client.guard.trip(TripKind.ERROR, f"parse failed: {reason}")
        raise CollectionBlocked(reason)


def _str_or_none(value: object) -> str | None:
    return None if value is None else str(value)


def minimal_terms(terms: Sequence[str]) -> list[str]:
    """대소문자만 다른 검색어와, 다른 검색어를 포함하는 검색어는 뺀다
    ("NVIDIA Corporation"은 "NVIDIA" 결과에 들어 있다). 검색어마다 요청이 하나씩 늘기 때문이다."""
    by_key: dict[str, str] = {}
    for t in terms:
        key = normalize_text(t)
        if key and key not in by_key:
            by_key[key] = t.strip()
    return [t for key, t in by_key.items() if not any(o != key and o in key for o in by_key)]

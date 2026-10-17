"""발견 공급자: 주제(노드 별칭)로 관련 글의 URL과 제목을 찾는다 (DECISIONS D24·D25).

- GDELT DOC 2.0: 키 없이 쓰는 공개 뉴스 색인. 5초에 한 번 넘게 부르면 429를 주므로
  PoliteClient의 최소 간격을 6초로 둔다. 문제가 생기면 GDELT 소스만 멈춘다 (BlockGuard).
- Brave Search: 선택적 공급자. MVP에서는 인터페이스만 두고 호출하지 않는다.

공급자는 글을 가져오지 않는다. URL·제목·처음 본 시각만 돌려주고, 실제 접근은 사이트 정책을
확인한 뒤 범용 수집기가 한다.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn, Protocol

import httpx

from narrative_radar.collectors.guard import CollectionBlocked, TripKind
from narrative_radar.collectors.http import PoliteClient

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_PARSER_VERSION = "gdelt.doc.v1"
GDELT_TIME_FORMAT = "%Y%m%d%H%M%S"
GDELT_MIN_TERM_LENGTH = 3  # 더 짧은 검색어는 GDELT가 거부한다
MAX_TERMS_PER_QUERY = 4


@dataclass(frozen=True)
class DiscoveredItem:
    url: str
    title: str
    seen_at: datetime  # 공급자가 처음 본 시각 (실제 게시 시각과 다를 수 있다)
    domain: str | None = None
    language: str | None = None
    source_country: str | None = None


class QueryRejected(ValueError):
    """공급자가 이 검색어만 거부했다 (너무 짧음·너무 흔함 등). 다른 검색은 계속한다."""


class ProviderDisabled(RuntimeError):
    """이 공급자는 꺼져 있다. 네트워크 요청을 하지 않는다."""


class DiscoveryProvider(Protocol):
    name: str
    enabled: bool

    def build_query(self, aliases: Sequence[str]) -> str | None:
        """노드 별칭으로 이 공급자의 검색식을 만든다. 쓸 수 있는 별칭이 없으면 None."""
        ...

    def search(
        self, query: str, start: datetime, end: datetime, max_records: int
    ) -> list[DiscoveredItem]: ...


# --- GDELT ---------------------------------------------------------------------------------

_BARE_TERM = re.compile(r"[A-Za-z0-9]+")


def gdelt_query(aliases: Sequence[str], max_terms: int = MAX_TERMS_PER_QUERY) -> str | None:
    """영문 별칭을 OR로 묶는다. 여러 단어·기호가 있으면 따옴표로 감싼다.

    GDELT는 번역된 영문 색인을 검색하므로 한글 별칭은 쓰지 않는다.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        text = " ".join(re.sub(r'["()]', " ", alias).split())
        if not text.isascii() or len(text) < GDELT_MIN_TERM_LENGTH or text.lower() in seen:
            continue
        seen.add(text.lower())
        terms.append(text if _BARE_TERM.fullmatch(text) else f'"{text}"')
        if len(terms) >= max_terms:
            break
    if not terms:
        return None
    return terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"


def parse_seendate(value: str) -> datetime:
    """GDELT `seendate` (예: 20261016T024500Z). ISO 형식도 받는다."""
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class GdeltProvider:
    name = "gdelt"
    enabled = True

    def __init__(self, client: PoliteClient) -> None:
        self.client = client

    def build_query(self, aliases: Sequence[str]) -> str | None:
        return gdelt_query(aliases)

    def search(
        self, query: str, start: datetime, end: datetime, max_records: int
    ) -> list[DiscoveredItem]:
        response = self.client.get(
            GDELT_DOC_API,
            {
                "query": query,
                "mode": "artlist",
                "format": "json",
                "maxrecords": str(max_records),
                "startdatetime": start.astimezone(UTC).strftime(GDELT_TIME_FORMAT),
                "enddatetime": end.astimezone(UTC).strftime(GDELT_TIME_FORMAT),
                "sort": "datedesc",
            },
        )
        return self._parse(response)

    def _parse(self, response: httpx.Response) -> list[DiscoveredItem]:
        if response.status_code != 200:
            self._stop(TripKind.ERROR, f"HTTP {response.status_code} from GDELT")
        text = response.text
        try:
            # GDELT 제목에는 이스케이프되지 않은 제어 문자가 섞일 때가 있다
            body = json.loads(text, strict=False)
        except ValueError:
            message = " ".join(text.split())[:300]
            if "limit requests" in message.lower():
                self._stop(TripKind.BLOCKED, f"GDELT rate limit: {message}")
            if not message or len(text) > 2000 or "<html" in text[:500].lower():
                self._stop(TripKind.ERROR, "unexpected non-JSON response from GDELT")
            raise QueryRejected(message) from None
        if not isinstance(body, dict):
            self._stop(TripKind.ERROR, "unexpected GDELT response shape")
        articles = body.get("articles", [])  # 결과가 없으면 빈 객체 {}가 온다
        if not isinstance(articles, list):
            self._stop(TripKind.ERROR, "unexpected GDELT articles field")
        return [self._item(a) for a in articles]

    def _item(self, article: Any) -> DiscoveredItem:
        try:
            url = article["url"]
            title = article.get("title") or ""
            if not isinstance(url, str) or not isinstance(title, str):
                raise TypeError("url/title must be strings")
            return DiscoveredItem(
                url=url,
                title=" ".join(title.split()),
                seen_at=parse_seendate(article["seendate"]),
                domain=_str_or_none(article.get("domain")),
                language=_str_or_none(article.get("language")),
                source_country=_str_or_none(article.get("sourcecountry")),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            self._stop(TripKind.ERROR, f"unexpected GDELT article shape: {e!r}")

    def _stop(self, kind: TripKind, reason: str) -> NoReturn:
        self.client.guard.trip(kind, reason)
        raise CollectionBlocked(reason)


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


# --- Brave Search (비활성) --------------------------------------------------------------------


class BraveSearchProvider:
    """선택적 발견 공급자. MVP에서는 호출하지 않는다 (DECISIONS D25).

    GDELT의 검색 범위나 발견 품질에 한계가 확인되면 도입을 다시 검토한다. 켜려면 결정 기록을
    바꾸고, 결과 저장 권한이 있는 요금제와 키(환경 시크릿)를 갖춘 뒤 search를 구현한다.
    """

    name = "brave"
    enabled = False

    def build_query(self, aliases: Sequence[str]) -> str | None:
        terms = [f'"{a}"' if " " in a else a for a in dict.fromkeys(aliases) if a.strip()]
        return " OR ".join(terms[:MAX_TERMS_PER_QUERY]) or None

    def search(
        self, query: str, start: datetime, end: datetime, max_records: int
    ) -> list[DiscoveredItem]:
        raise ProviderDisabled("Brave Search is disabled in the MVP (DECISIONS D25)")

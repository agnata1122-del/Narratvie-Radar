"""웹 페이지에서 본문·제목·게시 시각·수집 거부 표기를 뽑는다 (DECISIONS D24·D25).

외부 라이브러리 없이 표준 html.parser로 처리한다.
- 본문: <article> → <main> → 문서 전체 순서로, 문단·제목·목록 블록의 글만 모은다.
  메뉴·머리말·꼬리말·사이드바·폼·스크립트는 건너뛴다.
- 게시 시각: article:published_time 등 메타 태그 → JSON-LD datePublished → <time datetime>.
  시간대가 없는 값은 추측하지 않고 버린다.
- 수집 거부: <meta name="robots"> 또는 우리 이름(narrativeradar)의 메타 태그 지시어.
"""

import codecs
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser

AGENT_TOKEN = "narrativeradar"
MAX_TEXT_CHARS = 20_000
MIN_BLOCK_CHARS = 25  # 이보다 짧은 블록(버튼 글, 날짜 줄 등)은 본문으로 보지 않는다

_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "button",
        "iframe",
        "select",
        "figure",
    }
)
_BLOCK_TAGS = frozenset(
    {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "pre", "dd", "td", "div", "section"}
)
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4"})
_PUBLISHED_META = (
    "article:published_time",
    "og:article:published_time",
    "datepublished",
    "pubdate",
    "publishdate",
    "parsely-pub-date",
    "date",
    "dc.date.issued",
)
_CHARSET_RE = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_\-:.]+)""", re.I)


@dataclass(frozen=True)
class PageContent:
    title: str | None
    text: str
    published_at: datetime | None
    lang: str | None
    robots: frozenset[str] = field(default_factory=frozenset)


def decode_html(body: bytes, content_type: str) -> str:
    """응답 헤더의 charset → <meta charset> → UTF-8 순서로 해석한다."""
    charset = None
    for part in content_type.split(";")[1:]:
        key, _, value = part.partition("=")
        if key.strip().lower() == "charset":
            charset = value.strip().strip("\"'")
    if not charset:
        match = _CHARSET_RE.search(body[:4096])
        charset = match.group(1).decode("ascii", "ignore") if match else None
    try:
        codec = codecs.lookup(charset or "utf-8").name
    except LookupError:
        codec = "utf-8"
    return body.decode(codec, errors="replace")


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def robots_directives(value: str, agent: str = AGENT_TOKEN) -> set[str]:
    """`noindex, noai` 또는 `narrativeradar: noai` 같은 지시어. 다른 봇에게만 준 것은 뺀다."""
    out: set[str] = set()
    for raw in value.lower().split(","):
        item = raw.strip()
        if ":" in item:
            who, _, rest = item.partition(":")
            if who.strip() not in (agent, "*"):
                continue
            item = rest.strip()
        out.update(item.split())
    return out


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.robots: set[str] = set()
        self.json_ld: list[str] = []
        self.time_values: list[str] = []
        self.lang: str | None = None
        # (텍스트, article 안인가, main 안인가, 제목인가)
        self.blocks: list[tuple[str, bool, bool, bool]] = []
        self._skip: list[str] = []
        self._in_title = False
        self._in_json_ld = False
        self._article = 0
        self._main = 0
        self._buf: list[str] = []
        self._buf_heading = False

    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        if text:
            self.blocks.append((text, self._article > 0, self._main > 0, self._buf_heading))
        self._buf = []
        self._buf_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"][:16]
        elif tag == "meta":
            self._meta(a)
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_json_ld = True
        elif tag == "time" and a.get("datetime"):
            self.time_values.append(a["datetime"])
        if tag in _SKIP_TAGS:
            self._flush()
            self._skip.append(tag)
            return
        if tag == "article":
            self._flush()
            self._article += 1
        elif tag == "main":
            self._flush()
            self._main += 1
        elif tag in _BLOCK_TAGS or tag == "br":
            self._flush()
            self._buf_heading = tag in _HEADING_TAGS

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_json_ld = False
        if tag in _SKIP_TAGS:
            if tag in self._skip:
                while self._skip and self._skip.pop() != tag:
                    pass
            return
        if tag in _BLOCK_TAGS:
            self._flush()
        elif tag == "article" and self._article:
            self._flush()
            self._article -= 1
        elif tag == "main" and self._main:
            self._flush()
            self._main -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif self._in_json_ld:
            self.json_ld.append(data)
        elif not self._skip:
            self._buf.append(data)

    def _meta(self, a: dict[str, str]) -> None:
        key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
        content = a.get("content", "")
        if not key:
            return
        if key in ("robots", AGENT_TOKEN):
            self.robots |= robots_directives(content)
        self.meta.setdefault(key, content)

    def close(self) -> None:
        super().close()
        self._flush()


def _json_ld_published(chunks: list[str]) -> tuple[datetime | None, str | None]:
    for chunk in chunks:
        try:
            data = json.loads(chunk, strict=False)
        except ValueError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                published = parse_datetime(_as_str(item.get("datePublished")))
                if published is not None:
                    return published, _as_str(item.get("headline"))
                stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
    return None, None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def extract_page(html: str) -> PageContent:
    parser = _PageParser()
    parser.feed(html)
    parser.close()

    published = None
    for key in _PUBLISHED_META:
        published = parse_datetime(parser.meta.get(key))
        if published is not None:
            break
    ld_published, ld_headline = _json_ld_published(parser.json_ld)
    published = published or ld_published
    if published is None:
        published = next(
            (p for p in map(parse_datetime, parser.time_values) if p is not None), None
        )

    title = (
        parser.meta.get("og:title")
        or ld_headline
        or " ".join("".join(parser.title_parts).split())
        or None
    )

    def pick(blocks: list[tuple[str, bool, bool, bool]]) -> list[str]:
        return [t for t, _, _, heading in blocks if heading or len(t) >= MIN_BLOCK_CHARS]

    chosen: list[str] = []
    for scope in (
        [b for b in parser.blocks if b[1]],
        [b for b in parser.blocks if b[2]],
        parser.blocks,
    ):
        chosen = pick(scope)
        if sum(len(t) for t in chosen) >= 200:
            break
    text = "\n".join(dict.fromkeys(chosen))[:MAX_TEXT_CHARS]
    return PageContent(
        title=" ".join(title.split())[:500] if title else None,
        text=text,
        published_at=published,
        lang=parser.lang,
        robots=frozenset(parser.robots),
    )


# 사람 확인·차단 안내 페이지 (정상 페이지의 댓글 폼 reCAPTCHA 스크립트와 구분한다)
_CHALLENGE_HTML_MARKERS = ("/cdn-cgi/challenge-platform/", "cf-chl-", "_cf_chl_opt")
_CHALLENGE_TITLE_MARKERS = (
    "just a moment",
    "attention required",
    "access denied",
    "are you a robot",
    "security check",
    "보안 확인",
    "접근이 차단",
    "비정상적인 접근",
)
_CHALLENGE_TEXT_MARKERS = (
    "captcha",
    "verify you are human",
    "are you a robot",
    "unusual traffic",
    "보안문자",
    "자동입력 방지",
    "자동 입력 방지",
    "비정상적인 접근",
    "접근이 차단",
)


def looks_like_challenge(html: str, page: PageContent) -> bool:
    head = html[:20_000].lower()
    if any(m in head for m in _CHALLENGE_HTML_MARKERS):
        return True
    title = (page.title or "").lower()
    if any(m in title for m in _CHALLENGE_TITLE_MARKERS):
        return True
    # 본문이 짧은 안내 페이지에서만 본문 표지를 본다
    text = page.text.lower()
    return len(text) < 1500 and any(m in text for m in _CHALLENGE_TEXT_MARKERS)

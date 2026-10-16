"""HTML 조각을 분석용 평문으로 바꾼다. 링크는 주소를 남기고, 문단은 줄바꿈으로 나눈다."""

from html.parser import HTMLParser

_BLOCK_TAGS = frozenset({"p", "br", "div", "li", "pre", "blockquote", "tr"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = "".join(self._link_text).strip()
            if self._href and self._href not in text:
                self.parts.append(f" ({self._href})")
            self._href = None

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        if self._href is not None:
            self._link_text.append(data)


def html_to_text(fragment: str | None) -> str:
    if not fragment:
        return ""
    parser = _TextExtractor()
    parser.feed(fragment)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line).strip()

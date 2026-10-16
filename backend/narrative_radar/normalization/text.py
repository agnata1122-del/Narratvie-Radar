import hashlib
import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """비교용 정규화: NFKC, 대소문자 무시, 공백 정리. 저장되는 원문은 바꾸지 않는다."""
    return _WS.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()


def content_hash(title: str, body: str | None) -> str:
    """같은 내용의 재수집을 알아보기 위한 해시. 표기 차이(공백·전각 문자)는 무시한다."""
    payload = normalize_text(title) + "\n" + normalize_text(body or "")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

"""복사·전재 판정용 지문 (DECISIONS D6).

정규화한 본문의 단어 3-gram으로 64비트 SimHash를 만들고, 해밍 거리가 가까우면 같은 묶음으로 본다.
너무 짧은 글은 우연히 겹치기 쉬우므로 묶지 않는다.
"""

import hashlib
import re

from narrative_radar.normalization.text import normalize_text

MIN_TOKENS = 8
MAX_HAMMING = 3
_URL = re.compile(r"https?://\S+")
_TOKEN = re.compile(r"[\w$]+", re.UNICODE)


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(_URL.sub(" ", normalize_text(text)))


def simhash(text: str) -> int | None:
    toks = tokens(text)
    if len(toks) < MIN_TOKENS:
        return None
    grams = [" ".join(toks[i : i + 3]) for i in range(len(toks) - 2)]
    weights = [0] * 64
    for gram in grams:
        h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            weights[bit] += 1 if h >> bit & 1 else -1
    return sum(1 << bit for bit in range(64) if weights[bit] > 0)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def to_hex(value: int) -> str:
    return f"{value:016x}"


def from_hex(value: str) -> int:
    return int(value, 16)

"""시간순 정렬이 가능한 접두사 ID (`doc_01JA...`).

ULID와 같은 구성: 48비트 밀리초 타임스탬프 + 80비트 난수, Crockford base32 26자.

같은 밀리초에 만든 ID는 만든 순서대로 정렬되게 난수 부분을 1씩 올린다 (ULID monotonic).
이벤트는 (available_at, event_id) 순서로 접어서 상태를 만들기 때문에, 한 번의 반영에서 같은 시각으로
기록한 EDGE_CREATED → EDGE_CONFIRMED 순서가 뒤집히면 안 된다.
"""

import secrets
import threading
from datetime import datetime

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

PREFIXES = frozenset(
    {
        "cls",  # classification_runs
        "clm",  # claims
        "doc",  # documents
        "dgp",  # derivation_groups
        "edg",  # edges
        "evd",  # edge_evidence
        "evt",  # graph_events
        "fbk",  # classification_feedback
        "met",  # document_metric_snapshots
        "nar",  # narratives
        "nod",  # nodes
        "prf",  # interest_profiles
        "run",  # pipeline_runs
        "shl",  # source_health
        "vwr",  # viewers
        "vew",  # saved_views
        "wik",  # wiki_revisions
        "cmt",  # document_comments
        "als",  # node_aliases
        "nca",  # narrative_claims
        "pnd",  # profile_nodes
        "mnt",  # node_mentions
        "cnd",  # discovered_urls (수집 후보)
        "flg",  # fetch_logs
    }
)


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


_RANDOM_MAX = 2**80
_RECENT_LIMIT = 1024
_recent: dict[int, int] = {}  # 밀리초 → 그 밀리초에 마지막으로 쓴 난수 (최근 것만)
_lock = threading.Lock()


def _next_random(millis: int) -> int:
    with _lock:
        prev = _recent.pop(millis, None)
        value = secrets.randbits(80) if prev is None else prev + 1
        if value >= _RANDOM_MAX:
            raise OverflowError("too many ids in one millisecond")
        _recent[millis] = value
        while len(_recent) > _RECENT_LIMIT:
            _recent.pop(next(iter(_recent)))
        return value


def new_id(prefix: str, at: datetime) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix}")
    if at.tzinfo is None:
        raise ValueError("id timestamp must be timezone-aware")
    millis = int(at.timestamp() * 1000)
    if not 0 <= millis < 2**48:
        raise ValueError("timestamp out of range for id")
    return f"{prefix}_{_encode(millis, 10)}{_encode(_next_random(millis), 16)}"

"""시간순 정렬이 가능한 접두사 ID (`doc_01JA...`).

ULID와 같은 구성: 48비트 밀리초 타임스탬프 + 80비트 난수, Crockford base32 26자.
"""

import secrets
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
    }
)


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def new_id(prefix: str, at: datetime) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix}")
    if at.tzinfo is None:
        raise ValueError("id timestamp must be timezone-aware")
    millis = int(at.timestamp() * 1000)
    if not 0 <= millis < 2**48:
        raise ValueError("timestamp out of range for id")
    return f"{prefix}_{_encode(millis, 10)}{_encode(secrets.randbits(80), 16)}"

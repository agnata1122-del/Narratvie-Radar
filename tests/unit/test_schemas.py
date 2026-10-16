from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from narrative_radar.normalization.text import content_hash, normalize_text
from narrative_radar.schemas.document import DocumentIn
from narrative_radar.schemas.export import EXPORTS, render

REPO_ROOT = Path(__file__).resolve().parents[2]


def _doc(**overrides):
    base = {
        "source_adapter_id": "dcinside_stockus",
        "external_id": "123456",
        "source_url": "https://example.com/post/123456",
        "title": "example",
        "published_at": datetime(2026, 10, 13, 1, 0, tzinfo=UTC),
        "observed_at": datetime(2026, 10, 13, 1, 2, tzinfo=UTC),
        "content_access_status": "unverified",
        "ingest_mode": "live",
    }
    return DocumentIn(**(base | overrides))


def test_document_rejects_raw_author_identifier():
    with pytest.raises(ValidationError):
        _doc(author_hash="ㅇㅇ(1.234)")
    assert _doc(author_hash="a" * 64).author_hash == "a" * 64


def test_document_rejects_naive_timestamps():
    with pytest.raises(ValidationError):
        _doc(published_at=datetime(2026, 10, 13, 10, 0))  # noqa: DTZ001


def test_document_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        _doc(nickname="someone")


def test_normalization_ignores_width_case_and_spacing():
    assert normalize_text("  ＮＶＩＤＩＡ   Corporation ") == "nvidia corporation"
    assert content_hash("엔비디아  실적", "본문") == content_hash("엔비디아 실적", "본문 ")
    assert content_hash("a", "b") != content_hash("a", "c")


@pytest.mark.parametrize("name", sorted(EXPORTS))
def test_exported_json_schemas_are_up_to_date(name):
    path = REPO_ROOT / "schemas" / f"{name}.schema.json"
    assert path.exists(), "run: uv run nr schemas export"
    assert path.read_text(encoding="utf-8") == render(EXPORTS[name]), (
        "schema changed; run: uv run nr schemas export"
    )

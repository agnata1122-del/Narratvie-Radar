from datetime import UTC, datetime, timedelta, timezone

import pytest

from narrative_radar.core.clock import FixedClock, ensure_utc
from narrative_radar.core.ids import new_id


def test_ids_are_prefixed_and_time_sortable():
    t0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    earlier = new_id("doc", t0)
    later = new_id("doc", t0 + timedelta(milliseconds=1))
    assert earlier.startswith("doc_")
    assert len(earlier) == len("doc_") + 26
    assert earlier < later


def test_ids_reject_unknown_prefix_and_naive_time():
    with pytest.raises(ValueError):
        new_id("xyz", datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError):
        new_id("doc", datetime(2026, 1, 1))  # noqa: DTZ001


def test_ensure_utc_rejects_naive_and_normalizes_offsets():
    kst = timezone(timedelta(hours=9))
    assert ensure_utc(datetime(2026, 10, 13, 10, 0, tzinfo=kst)) == datetime(
        2026, 10, 13, 1, 0, tzinfo=UTC
    )
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 10, 13, 10, 0))  # noqa: DTZ001


def test_fixed_clock_only_moves_when_advanced():
    clock = FixedClock(datetime(2026, 10, 16, tzinfo=UTC))
    first = clock.now()
    assert clock.now() == first
    clock.advance(timedelta(minutes=5))
    assert clock.now() - first == timedelta(minutes=5)

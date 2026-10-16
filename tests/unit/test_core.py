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


def test_ids_made_in_the_same_millisecond_keep_creation_order():
    # 한 번의 반영에서 같은 시각으로 기록한 이벤트를 접는 순서가 뒤집히면 안 된다
    t0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    ids = [new_id("evt", t0) for _ in range(500)]
    assert ids == sorted(ids) and len(set(ids)) == 500
    other = new_id("evt", t0 - timedelta(seconds=1))  # 다른 시각이 끼어도
    assert new_id("evt", t0) > ids[-1] > other


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

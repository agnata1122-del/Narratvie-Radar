from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from narrative_radar.core.clock import FixedClock
from narrative_radar.db.migrate import upgrade_to_head
from narrative_radar.db.session import make_engine, make_session_factory


@pytest.fixture(autouse=True)
def _no_live_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """수집 환경의 실제 스위치·salt가 테스트에 섞이지 않게 한다. 필요한 테스트는 직접 넣는다."""
    monkeypatch.delenv("NR_LIVE_COLLECTION_ENABLED", raising=False)
    monkeypatch.delenv("NR_AUTHOR_HASH_SALT", raising=False)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 10, 16, 3, 0, tzinfo=UTC))


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    upgrade_to_head(url)
    return url


@pytest.fixture
def session_factory(db_url: str) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(db_url)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as s:
        yield s

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from narrative_radar.core.clock import FixedClock
from narrative_radar.db.migrate import upgrade_to_head
from narrative_radar.db.session import make_engine, make_session_factory


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

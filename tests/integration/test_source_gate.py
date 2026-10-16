import sqlalchemy as sa
from typer.testing import CliRunner

from narrative_radar.cli import app
from narrative_radar.collectors.gate import can_collect, mark_blocked, set_status
from narrative_radar.core.config import Settings
from narrative_radar.db.models import SourceAdapter
from narrative_radar.db.seed import seed_defaults
from narrative_radar.schemas.enums import SourceAccessStatus


def _adapter(session) -> SourceAdapter:
    return session.get(SourceAdapter, "dcinside_stockus")


def test_collection_requires_global_switch_source_switch_live_status_and_salt(session, clock):
    seed_defaults(session, clock)
    adapter = _adapter(session)
    on = Settings(live_collection_enabled=True, author_hash_salt="x" * 32)

    assert not can_collect(on, adapter).allowed  # 기본값: not_authorized

    set_status(session, adapter.source_adapter_id, SourceAccessStatus.LIVE, "t", clock, True)
    assert can_collect(on, adapter).allowed
    assert not can_collect(
        Settings(live_collection_enabled=False, author_hash_salt="x" * 32), adapter
    ).allowed
    assert not can_collect(Settings(live_collection_enabled=True), adapter).allowed

    mark_blocked(session, adapter.source_adapter_id, "HTTP 403", clock)
    assert adapter.access_status == SourceAccessStatus.BLOCKED
    assert adapter.live_enabled is False
    assert not can_collect(on, adapter).allowed


def test_cli_enable_requires_explicit_policy_acknowledgement(db_url, session, clock, monkeypatch):
    seed_defaults(session, clock)
    session.commit()
    monkeypatch.setenv("NR_DB_PATH", db_url.removeprefix("sqlite:///"))
    from narrative_radar.core.config import get_settings

    get_settings.cache_clear()
    runner = CliRunner()
    try:
        result = runner.invoke(app, ["sources", "enable", "dcinside_stockus"])
        assert result.exit_code == 2
        session.expire_all()
        assert _adapter(session).access_status == SourceAccessStatus.NOT_AUTHORIZED

        result = runner.invoke(
            app, ["sources", "enable", "dcinside_stockus", "--accept-data-policy"]
        )
        assert result.exit_code == 0, result.output
        session.expire_all()
        assert _adapter(session).access_status == SourceAccessStatus.LIVE

        # 차단되지 않은 소스는 reset할 수 없다
        result = runner.invoke(app, ["sources", "reset", "dcinside_stockus", "--reason", "x"])
        assert result.exit_code == 1

        mark_blocked(session, "dcinside_stockus", "HTTP 403", clock)
        session.commit()
        result = runner.invoke(
            app, ["sources", "reset", "dcinside_stockus", "--reason", "rate too high"]
        )
        assert result.exit_code == 0, result.output
        session.expire_all()
        adapter = _adapter(session)
        assert adapter.access_status == SourceAccessStatus.PAUSED
        assert adapter.live_enabled is False
        assert session.scalar(sa.select(sa.func.count()).select_from(SourceAdapter)) == 2
    finally:
        get_settings.cache_clear()

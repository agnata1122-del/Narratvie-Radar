"""DB 스냅숏 내보내기·가져오기 (비공개 데이터 저장소용)."""

from pathlib import Path

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from narrative_radar.db import snapshot
from narrative_radar.db.models import InterestProfile, SourceAdapter
from narrative_radar.db.seed import seed_defaults
from narrative_radar.db.session import make_engine, make_session_factory
from narrative_radar.db.snapshot import SnapshotError, export_snapshot, import_snapshot


def _count(url, model):
    engine = make_engine(url)
    with make_session_factory(engine)() as s:
        n = s.scalar(sa.select(sa.func.count()).select_from(model))
    engine.dispose()
    return n


def test_round_trip_in_parts_with_checksums(db_url, session_factory, clock, tmp_path, monkeypatch):
    with session_factory.begin() as s:
        seed_defaults(s, clock)
    monkeypatch.setattr(snapshot, "PART_BYTES", 4096)  # 여러 조각으로 나뉘게
    src = Path(db_url.removeprefix("sqlite:///"))
    out = tmp_path / "data-repo" / "snapshot"
    info = export_snapshot(src, out, clock.now())
    assert len(info.parts) > 1 and info.counts["source_adapters"] > 0

    restored = tmp_path / "restored" / "nr.db"
    import_snapshot(out, restored)
    url = f"sqlite:///{restored}"
    assert _count(url, SourceAdapter) == info.counts["source_adapters"]
    assert _count(url, InterestProfile) == 1

    with pytest.raises(SnapshotError, match="already exists"):
        import_snapshot(out, restored)
    (out / info.parts[0]).write_bytes(b"tampered")
    with pytest.raises(SnapshotError, match="corrupted part"):
        import_snapshot(out, restored, force=True)


def test_cli_refuses_to_export_into_the_public_code_repo(
    db_url, session_factory, clock, monkeypatch
):
    with session_factory.begin() as s:
        seed_defaults(s, clock)
    monkeypatch.setenv("NR_DB_PATH", db_url.removeprefix("sqlite:///"))
    from narrative_radar.cli import app
    from narrative_radar.core.config import get_settings

    get_settings.cache_clear()
    try:
        code_repo = Path(__file__).resolve().parents[2]
        result = CliRunner().invoke(app, ["data", "export", str(code_repo / "data" / "snap")])
        assert result.exit_code == 2 and "공개 코드 저장소" in result.output
        assert not (code_repo / "data" / "snap").exists()
    finally:
        get_settings.cache_clear()

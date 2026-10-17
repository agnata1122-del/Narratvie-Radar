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


def _put_text(url, text):
    """확인용: 아무 문자열이나 DB에 넣는다 (긴급 중단 사유 칸)."""
    engine = make_engine(url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO control_flags (key, enabled, reason, updated_at) "
                "VALUES ('probe', 0, :r, '2026-10-16T03:00:00+00:00')"
            ),
            {"r": text},
        )
    engine.dispose()


def test_export_refuses_when_a_secret_value_is_in_the_database(db_url, tmp_path):
    salt = "example-salt-value-0123456789abcdef"  # 형식 확인용 예시 값
    _put_text(db_url, f"oops {salt}")
    src = Path(db_url.removeprefix("sqlite:///"))
    out = tmp_path / "snap"
    with pytest.raises(SnapshotError, match=r"value of \$NR_AUTHOR_HASH_SALT") as err:
        export_snapshot(
            src, out, datetime_now(), env={"NR_AUTHOR_HASH_SALT": salt, "HOME": "/root"}
        )
    assert salt not in str(err.value)  # 값은 보고하지 않는다
    assert not out.exists()  # 아무것도 쓰지 않았다


def test_export_refuses_known_credential_formats(db_url, tmp_path):
    _put_text(db_url, "token ghp_" + "A" * 36)
    src = Path(db_url.removeprefix("sqlite:///"))
    with pytest.raises(SnapshotError, match="GitHub token"):
        export_snapshot(src, tmp_path / "snap", datetime_now(), env={})


def test_clean_export_records_the_secret_check(db_url, tmp_path):
    import json

    src = Path(db_url.removeprefix("sqlite:///"))
    out = tmp_path / "snap"
    export_snapshot(src, out, datetime_now(), env={"GH_TOKEN": "x" * 40, "PATH": "/usr/bin"})
    check = json.loads((out / "manifest.json").read_text())["secret_check"]
    assert check["result"] == "clean" and check["env_values_checked"] == 1


def datetime_now():
    from datetime import UTC, datetime

    return datetime(2026, 10, 16, 3, 0, tzinfo=UTC)

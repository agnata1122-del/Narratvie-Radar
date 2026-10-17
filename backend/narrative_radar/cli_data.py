"""`nr data …`: 수집 데이터를 비공개 데이터 저장소로 내보내고 받는다 (docs/OPERATIONS.md)."""

from pathlib import Path

import typer

from narrative_radar.core.config import get_settings

data_app = typer.Typer(help="DB 스냅숏 (비공개 데이터 저장소 전용)", no_args_is_help=True)


def _refuse_public_repo(path: Path) -> None:
    """이 코드 저장소 안으로는 내보내지 않는다. 공개 저장소에 원문이 올라가면 안 된다
    (DATA_POLICY 9)."""
    code_root = Path(__file__).resolve().parents[2]
    target = path.resolve()
    if target == code_root or code_root in target.parents:
        typer.echo(f"{path}는 공개 코드 저장소 안입니다. 비공개 데이터 저장소 경로를 주세요.")
        raise typer.Exit(code=2)


@data_app.command("export")
def data_export(out_dir: Path = typer.Argument(..., help="비공개 데이터 저장소 안의 폴더")) -> None:
    """DB를 압축·분할해 out_dir에 쓴다 (조각 + manifest.json)."""
    from narrative_radar.core.clock import SystemClock
    from narrative_radar.db.snapshot import SnapshotError, export_snapshot

    _refuse_public_repo(out_dir)
    try:
        info = export_snapshot(get_settings().db_path, out_dir, SystemClock().now())
    except SnapshotError as e:
        typer.echo(f"내보내지 못했습니다: {e}")
        raise typer.Exit(code=1) from e
    typer.echo(
        f"exported {len(info.parts)} part(s), {info.compressed_bytes:,} bytes "
        f"(db {info.database_bytes:,}); documents={info.counts.get('documents', 0)}"
    )


@data_app.command("import")
def data_import(
    in_dir: Path = typer.Argument(..., help="manifest.json이 있는 폴더"),
    force: bool = typer.Option(False, help="이미 있는 DB를 바꾼다"),
) -> None:
    """스냅숏을 확인(해시·행 수)한 뒤 DB로 풀고 마이그레이션을 최신으로 올린다."""
    from narrative_radar.db.snapshot import SnapshotError, import_snapshot

    try:
        info = import_snapshot(in_dir, get_settings().db_path, force=force)
    except SnapshotError as e:
        typer.echo(f"가져오지 못했습니다: {e}")
        raise typer.Exit(code=1) from e
    typer.echo(f"imported {len(info.parts)} part(s); documents={info.counts.get('documents', 0)}")

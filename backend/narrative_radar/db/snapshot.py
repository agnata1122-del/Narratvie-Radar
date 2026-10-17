"""DB 스냅숏: 세션 사이에 수집 데이터를 비공개 데이터 저장소로 옮긴다 (docs/OPERATIONS.md).

클라우드 컨테이너는 세션이 끝나면 사라진다. 주기 실행은 시작할 때 스냅숏을 받아 이어 쓰고,
끝날 때 다시 내보낸다. 공개 저장소에는 절대 올리지 않는다 (DATA_POLICY 9).

- 내보내기: SQLite 온라인 백업으로 일관된 사본을 만들고 gzip으로 압축한다. GitHub 파일 크기
  제한(100MB)에 걸리지 않게 조각으로 나누고, 조각마다 SHA-256을 manifest.json에 적는다.
- 가져오기: 조각을 이어 붙여 해시를 확인한 뒤 풀고, 마이그레이션을 최신으로 올린다.
  이미 DB가 있으면 덮어쓰지 않는다(--force일 때만).
"""

import gzip
import hashlib
import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from narrative_radar.db.migrate import upgrade_to_head

MANIFEST = "manifest.json"
PART_PREFIX = "narrative-radar.db.gz.part-"
PART_BYTES = 45 * 1024 * 1024  # GitHub 경고(50MB)보다 작게
FORMAT = "narrative-radar-snapshot.v1"


class SnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotInfo:
    parts: list[str]
    compressed_bytes: int
    database_bytes: int
    counts: dict[str, int]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _counts(db: Path) -> dict[str, int]:
    """확인용 행 수. 표 이름만 쓰고 내용은 읽지 않는다."""
    with sqlite3.connect(db) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def export_snapshot(db_path: Path, out_dir: Path, exported_at: datetime) -> SnapshotInfo:
    if not db_path.exists():
        raise SnapshotError(f"database not found: {db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "copy.db"
        # 실행 중인 DB도 일관된 사본을 만든다 (WAL 포함)
        with sqlite3.connect(db_path) as src, sqlite3.connect(copy) as dst:
            src.backup(dst)
        counts = _counts(copy)
        packed = Path(tmp) / "copy.db.gz"
        with copy.open("rb") as f_in, gzip.open(packed, "wb", compresslevel=9) as f_out:
            shutil.copyfileobj(f_in, f_out)

        for old in out_dir.glob(f"{PART_PREFIX}*"):
            old.unlink()
        parts = []
        with packed.open("rb") as f:
            for i, chunk in enumerate(iter(lambda: f.read(PART_BYTES), b"")):
                name = f"{PART_PREFIX}{i:03d}"
                (out_dir / name).write_bytes(chunk)
                parts.append(name)
        manifest = {
            "format": FORMAT,
            "exported_at": exported_at.isoformat(),
            "database_bytes": copy.stat().st_size,
            "compressed_bytes": packed.stat().st_size,
            "sha256": _sha256(packed),
            "parts": [{"name": p, "sha256": _sha256(out_dir / p)} for p in parts],
            "counts": counts,
        }
        (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return SnapshotInfo(parts, manifest["compressed_bytes"], manifest["database_bytes"], counts)


def import_snapshot(in_dir: Path, db_path: Path, force: bool = False) -> SnapshotInfo:
    manifest_path = in_dir / MANIFEST
    if not manifest_path.exists():
        raise SnapshotError(f"no {MANIFEST} in {in_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT:
        raise SnapshotError(f"unknown snapshot format: {manifest.get('format')!r}")
    if db_path.exists() and not force:
        raise SnapshotError(f"{db_path} already exists (use --force to replace it)")

    with tempfile.TemporaryDirectory() as tmp:
        packed = Path(tmp) / "copy.db.gz"
        with packed.open("wb") as out:
            for part in manifest["parts"]:
                path = in_dir / part["name"]
                if not path.exists() or _sha256(path) != part["sha256"]:
                    raise SnapshotError(f"missing or corrupted part: {part['name']}")
                out.write(path.read_bytes())
        if _sha256(packed) != manifest["sha256"]:
            raise SnapshotError("snapshot checksum mismatch")
        restored = Path(tmp) / "restored.db"
        with gzip.open(packed, "rb") as f_in, restored.open("wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        if _counts(restored) != manifest["counts"]:
            raise SnapshotError("restored row counts differ from the manifest")

        db_path.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)
        shutil.move(restored, db_path)
    upgrade_to_head(f"sqlite:///{db_path}")
    return SnapshotInfo(
        [p["name"] for p in manifest["parts"]],
        manifest["compressed_bytes"],
        manifest["database_bytes"],
        manifest["counts"],
    )

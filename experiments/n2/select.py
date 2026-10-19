"""N2′ 대상 글 내보내기 (docs/EXPERIMENTS.md "N2′").

E1 분석 창 안에서 v3 분류가 accepted이고 잡음이 아니며 메모리 3사가 개체로 나온 글을
50개씩 나눠 쓴다. 글마다 원문과 대상 이름(개체 중 대상 기업의 이름)을 담는다.
출력에 원문이 들어가므로 비공개 작업 폴더·데이터 저장소에만 둔다.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from narrative_radar.classifiers.session import _source_text
from narrative_radar.core.config import get_settings
from narrative_radar.db.models import ClassificationRun, Document
from narrative_radar.db.session import make_engine, make_session_factory
from narrative_radar.schemas import extraction
from narrative_radar.schemas.enums import ClassificationStatus

WINDOW = (datetime(2025, 10, 20, tzinfo=UTC), datetime(2026, 10, 17, tzinfo=UTC))
MEMORY = {"US:MU", "KR:000660", "KR:005930"}
TARGETS = MEMORY | {"US:NVDA"}
BATCH = 50


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    session = make_session_factory(make_engine(get_settings().database_url))()
    rows = session.execute(
        sa.select(Document, ClassificationRun)
        .join(ClassificationRun, ClassificationRun.document_id == Document.document_id)
        .where(
            ClassificationRun.schema_version == extraction.SCHEMA_VERSION,
            ClassificationRun.status == ClassificationStatus.ACCEPTED,
            ClassificationRun.content_hash == Document.content_hash,
            Document.published_at >= WINDOW[0],
            Document.published_at < WINDOW[1],
        )
        .order_by(Document.published_at, Document.document_id)
    ).all()
    posts = []
    for doc, cls in rows:
        out = cls.output
        if out["is_noise"]:
            continue
        keys = {e.get("canonical_key") for e in out["entities"]}
        if not keys & MEMORY:
            continue
        targets = sorted(
            {e["name"]: e["canonical_key"] for e in out["entities"]
             if e.get("canonical_key") in TARGETS}.items()
        )  # fmt: skip
        posts.append(
            {
                "document_id": doc.document_id,
                "published_at": doc.published_at.isoformat(),
                "targets": [{"name": n, "key": k} for n, k in targets],
                "text": _source_text(session, doc),
            }
        )
    for i in range(0, len(posts), BATCH):
        d = args.out / f"n{i // BATCH:02d}.d"
        d.mkdir(parents=True, exist_ok=True)
        with (d / "batch.jsonl").open("w", encoding="utf-8") as f:
            for p in posts[i : i + BATCH]:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"posts={len(posts)} batches={(len(posts) + BATCH - 1) // BATCH}")


if __name__ == "__main__":
    main()

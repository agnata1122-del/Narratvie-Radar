"""E1 분류 대상 고르기 (docs/EXPERIMENTS.md E1).

분석 창 안에서 메모리 키워드가 단어 단위로 들어간 글의 ID를 고르고, 재현용 메타데이터와
분류 비용 추정치를 남긴다. DB는 읽기만 한다. 결과는 data/ 아래에 둔다(커밋하지 않음).

    uv run python experiments/e1/select_targets.py \\
        --start 2025-10-20 --end 2026-10-17 --manifest <스냅숏>/manifest.json
    uv run nr classify pending --ids-file data/work/e1/ids.txt --limit 50 ...
"""

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from narrative_radar.classifiers.session import GUIDELINES, MAX_TEXT_CHARS
from narrative_radar.core.config import get_settings
from narrative_radar.db.models import Document, RawDocument
from narrative_radar.db.session import make_engine, make_session_factory
from narrative_radar.domains.registry import get_pack
from narrative_radar.normalization.text import normalize_text, term_pattern

# 실험 전에 고정한 검색어 (EXPERIMENTS.md E1 "분류 범위"). 바꾸면 결과를 비교할 수 없다
TERMS = (
    "HBM",
    "high bandwidth memory",
    "고대역폭 메모리",
    "Hynix",
    "SK하이닉스",
    "하이닉스",
    "하닉",
    "Samsung Electronics",
    "삼성전자",
    "삼전",
    "Micron",
    "마이크론",
)
SOURCES = ("hackernews", "reddit_arctic")  # Bluesky는 과거분이 없어 쓰지 않는다
BATCH = 50
# 비용 추정 가정: 영어 4자당 1토큰, 한글 1자당 1토큰, 출력은 글당 250토큰
OUTPUT_TOKENS_PER_DOC = 250


def _tokens(text: str) -> int:
    hangul = sum(1 for ch in text if "가" <= ch <= "힣")
    return hangul + (len(text) - hangul) // 4


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="게시 시각 하한 (UTC 날짜, 포함)")
    ap.add_argument("--end", required=True, help="게시 시각 상한 (UTC 날짜, 제외)")
    ap.add_argument("--manifest", type=Path, required=True, help="쓴 스냅숏의 manifest.json")
    ap.add_argument("--out-dir", type=Path, default=Path("data/work/e1"))
    args = ap.parse_args()

    patterns = [term_pattern(t) for t in TERMS]
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    factory = make_session_factory(make_engine(get_settings().database_url))
    ids: list[str] = []
    by_source: Counter[str] = Counter()
    by_month: Counter[str] = Counter()
    input_tokens = 0
    with factory() as session:
        rows = session.execute(
            sa.select(
                Document.document_id,
                Document.source_adapter_id,
                Document.published_at,
                Document.title,
                RawDocument.body_text,
            )
            .outerjoin(RawDocument, RawDocument.document_id == Document.document_id)
            .where(
                Document.source_adapter_id.in_(SOURCES),
                Document.deleted_observed_at.is_(None),
                Document.published_at >= start,
                Document.published_at < end,
            )
            .order_by(Document.published_at)
        )
        for doc_id, source, published, title, body in rows:
            text = "\n".join(p for p in (title, body) if p)
            if not any(p.search(normalize_text(text)) for p in patterns):
                continue
            ids.append(doc_id)
            by_source[source] += 1
            by_month[published.strftime("%Y-%m")] += 1
            input_tokens += _tokens(text[:MAX_TEXT_CHARS])

    pack = get_pack("finance")
    guideline_tokens = sum(
        _tokens(p.read_text(encoding="utf-8")) for p in (GUIDELINES, pack.guideline) if p
    )
    batches = -(-len(ids) // BATCH)
    estimate = {
        "documents": len(ids),
        "batches_of_50": batches,
        "input_tokens_documents": input_tokens,
        "input_tokens_guidelines_per_batch": guideline_tokens,
        "input_tokens_total": input_tokens + guideline_tokens * batches,
        "output_tokens_total": OUTPUT_TOKENS_PER_DOC * len(ids),
        "assumptions": "영어 4자=1토큰, 한글 1자=1토큰, 출력 글당 250토큰, 배치마다 지침 1회",
    }
    manifest = args.manifest.read_bytes()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    meta = {
        "experiment": "E1",
        "created_at": datetime.now(UTC).isoformat(),
        "window": {"start": args.start, "end_exclusive": args.end},
        "terms": TERMS,
        "sources": SOURCES,
        "snapshot_manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "snapshot_exported_at": json.loads(manifest).get("exported_at"),
        "code_commit": commit,
        "by_source": dict(by_source),
        "by_month": dict(sorted(by_month.items())),
        "cost_estimate": estimate,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "ids.txt").write_text("".join(f"{i}\n" for i in ids), encoding="utf-8")
    (args.out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: meta[k] for k in ("by_source", "cost_estimate")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

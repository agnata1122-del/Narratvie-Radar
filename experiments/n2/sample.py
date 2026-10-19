"""N2′ 정확도 표본 (docs/EXPERIMENTS.md "N2′").

배치마다 batch.jsonl·out.jsonl·ground.jsonl을 읽어
- impacts.jsonl: 추출된 영향 전부(근거 검증 판정 포함)
- units.jsonl: 무작위 50개(시드 20261019) 판정 단위. 원문·발췌만 담고 근거 검증 판정은 넣지 않는다
- missed.jsonl: 영향이 없다고 한 글 무작위 20건(참고용 누락 점검)
을 쓰고 개수를 출력한다. 출력에 원문이 들어가므로 비공개 작업 폴더·데이터 저장소에만 둔다.
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

SEED = 20261019
SAMPLE = 50
MISSED = 20


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path, help="배치 폴더(nNN.d)가 있는 폴더")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    impacts, empty = [], []
    for d in sorted(args.run.glob("n*.d")):
        posts, outs = _lines(d / "batch.jsonl"), _lines(d / "out.jsonl")
        ground = _lines(d / "ground.jsonl")
        for p, o, g in zip(posts, outs, ground, strict=True):
            assert p["document_id"] == o["document_id"] == g["document_id"]
            verdicts = {v["index"]: v for v in g["verdicts"]}
            if not o["impacts"]:
                empty.append(p)
            for i, m in enumerate(o["impacts"]):
                key = next(t["key"] for t in p["targets"] if t["name"] == m["target"])
                impacts.append(
                    {
                        "document_id": p["document_id"],
                        "published_at": p["published_at"],
                        "index": i,
                        "key": key,
                        **m,
                        "grounding": verdicts[i]["verdict"],
                        "issue": verdicts[i].get("issue"),
                    }
                )
    with (args.out / "impacts.jsonl").open("w", encoding="utf-8") as f:
        for m in impacts:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    texts = {p["document_id"]: p["text"] for d in args.run.glob("n*.d")
             for p in _lines(d / "batch.jsonl")}  # fmt: skip
    rng = random.Random(SEED)
    picked = rng.sample(impacts, min(SAMPLE, len(impacts)))
    with (args.out / "units.jsonl").open("w", encoding="utf-8") as f:
        for n, m in enumerate(picked, 1):
            unit = {
                "uid": f"I{n:02d}",
                "document_id": m["document_id"],
                "index": m["index"],
                "target": m["target"],
                "direction": m["direction"],
                "modality": m["modality"],
                "excerpt": m["excerpt"],
                "text": texts[m["document_id"]],
            }
            f.write(json.dumps(unit, ensure_ascii=False) + "\n")
    with (args.out / "missed.jsonl").open("w", encoding="utf-8") as f:
        for n, p in enumerate(rng.sample(empty, min(MISSED, len(empty))), 1):
            f.write(json.dumps({"uid": f"M{n:02d}", **p}, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "impacts": len(impacts),
                "posts_with_impacts": len({m["document_id"] for m in impacts}),
                "direction": Counter(m["direction"] for m in impacts),
                "grounding": Counter(m["grounding"] for m in impacts),
                "target": Counter(m["key"] for m in impacts),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

"""R1-X 새 표본 추출 (docs/EXPERIMENTS.md "R1-X").

E1 대상 중 어떤 표본에도 쓰지 않은 글에서, 분류 결과와 무관하게 원문에 인과 표현이 있는 글만 골라
시드 고정으로 뽑는다. v2·v3 어느 쪽 출력도 보지 않으므로 두 방식에 중립이다.
`--negative`는 인과 표현이 없는 글에서 뽑는 보조 음성 대조군이다(주 평가에 섞지 않는다).
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

# 원문 인과 표현 (영어·한국어). 분류 결과가 아니라 글 자체로만 고른다
CAUSAL = re.compile(
    r"\b(because|due to|caused by|leads? to|led to|result(?:s|ed)? in|as a result|"
    r"driven by|thanks to|therefore|hence|which means|so that)\b"
    r"|때문|로 인해|탓에|덕분에|그래서|따라서",
    re.IGNORECASE,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True, help="E1 대상 목록")
    ap.add_argument("--batch-files", nargs="+", required=True, help="원문이 든 batch.jsonl들")
    ap.add_argument("--exclude", nargs="+", default=[], help="이미 쓴 표본 jsonl (document_id)")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=20261021)
    ap.add_argument(
        "--negative", action="store_true", help="인과 표현이 없는 글에서 뽑는다 (음성 대조군)"
    )
    args = ap.parse_args()

    targets = set(Path(args.ids).read_text().split())
    used = set()
    for p in args.exclude:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                used.add(json.loads(line)["document_id"])
    texts = {}
    for p in args.batch_files:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                texts[rec["document_id"]] = rec
    pool = sorted(
        d
        for d in targets - used
        if d in texts and bool(CAUSAL.search(texts[d].get("text") or "")) != args.negative
    )
    picked = sorted(random.Random(args.seed).sample(pool, args.n))
    meta = {"pool": len(pool), "excluded": len(used & targets), "n": len(picked), "seed": args.seed}
    print(json.dumps(meta), file=sys.stderr)
    for d in picked:
        print(d)


if __name__ == "__main__":
    main()

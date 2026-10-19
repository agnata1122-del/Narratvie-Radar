"""N2′ 추출·근거 검증 결과의 형식 검사 (docs/EXPERIMENTS.md "N2′").

사용: python experiments/n2/check.py BATCH_DIR [--ground]
- 줄 수·순서·document_id가 batch.jsonl과 같은지
- 대상이 그 글의 대상 이름 중 하나인지, 값이 정해진 것인지, 발췌가 원문 그대로이고 200자 이하인지
- --ground: 항목마다 판정이 정확히 하나인지
의미 판정은 하지 않는다. 문제가 있으면 줄 번호와 이유를 출력하고 종료 코드 1.
"""

import argparse
import json
import sys
from pathlib import Path

DIRECTIONS = {"up", "down", "mixed"}
MODALITIES = {"actual", "expected", "conditional"}
ATTRIBUTIONS = {"author", "reported", "official"}
VERDICTS = {"entailed", "partial", "not_entailed"}
MAX_IMPACTS = 6


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def check(d: Path, ground: bool) -> list[str]:
    posts, outs = _lines(d / "batch.jsonl"), _lines(d / "out.jsonl")
    errors = []
    if len(posts) != len(outs):
        return [f"{len(outs)} lines for {len(posts)} posts"]
    verdicts = _lines(d / "ground.jsonl") if ground else []
    if ground and len(verdicts) != len(posts):
        return [f"{len(verdicts)} grounding lines for {len(posts)} posts"]
    for i, (p, o) in enumerate(zip(posts, outs, strict=True), 1):
        if o.get("document_id") != p["document_id"]:
            errors.append(f"line {i}: document_id out of order")
            continue
        names = {t["name"] for t in p["targets"]}
        impacts = o.get("impacts")
        if not isinstance(impacts, list) or len(impacts) > MAX_IMPACTS:
            errors.append(f"line {i}: impacts must be a list of at most {MAX_IMPACTS}")
            continue
        for j, m in enumerate(impacts):
            where = f"line {i} impact {j}"
            if m.get("target") not in names:
                errors.append(f"{where}: target {m.get('target')!r} is not one of {sorted(names)}")
            for field, allowed in (
                ("direction", DIRECTIONS),
                ("modality", MODALITIES),
                ("attribution", ATTRIBUTIONS),
            ):
                if m.get(field) not in allowed:
                    errors.append(f"{where}: {field} {m.get(field)!r}")
            ex = m.get("excerpt") or ""
            if not ex or len(ex) > 200 or ex not in p["text"]:
                errors.append(f"{where}: excerpt is not a verbatim quote of at most 200 chars")
        if ground:
            g = verdicts[i - 1]
            idx = sorted(v.get("index") for v in g.get("verdicts", []))
            if g.get("document_id") != p["document_id"] or idx != list(range(len(impacts))):
                errors.append(f"line {i}: grounding does not cover each impact exactly once")
            elif any(v.get("verdict") not in VERDICTS for v in g["verdicts"]):
                errors.append(f"line {i}: unknown verdict")
    return errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--ground", action="store_true")
    args = ap.parse_args()
    errors = check(args.dir, args.ground)
    for e in errors:
        print(e)
    print(f"{args.dir.name}: {'ok' if not errors else f'{len(errors)} problems'}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

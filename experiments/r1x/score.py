"""R1-X 채점 (docs/EXPERIMENTS.md "R1-X", DECISIONS D37).

입력: 평가 단위(fresh_units.jsonl), 두 AI 판정(J1·J2), v3 근거 검증(ground_v3.jsonl),
v2 ingest 결과(review 글 목록), 소유자 답(선택). 판정 규칙:
- 소유자가 본 단위는 소유자 답, 나머지는 J1·J2 합의. 둘이 갈렸는데 소유자 답이 없으면 미정.
- 검산 단위에서 소유자가 AI 합의와 다르게 본 것이 2개 이상이면 AI 합의를 쓰지 않는다(판정 보류).
지표 정의는 D37을 따른다. 채택 판단은 사람이 한다.
"""

import argparse
import json
from collections import Counter
from pathlib import Path


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _judge(path: Path) -> dict:
    return {(r["document_id"], j["uid"]): j for r in _lines(path) for j in r["judgments"]}


def _grounding(run: Path, batches: list[str]) -> dict:
    out = {}
    for b in batches:
        for r in _lines(run / b / "ground_v3.jsonl"):
            for v in r["verdicts"]:
                prefix = {"event": "v3e", "causal_link": "v3l", "claim": "v3c"}[v["kind"]]
                out[(r["document_id"], f"{prefix}{v['index']}")] = v
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="r1xrun 폴더 (배치별 out·ground 파일)")
    ap.add_argument("--batches", nargs="+", default=["F1", "F2"])
    ap.add_argument("--v2-review", nargs="*", default=[], help="v2 ingest에서 review된 document_id")
    ap.add_argument("--owner", help='소유자 답 {"doc|uid": "yes|no|unsure"}')
    ap.add_argument("--owner-set", help="owner_set.json (disagree·audit 목록)")
    args = ap.parse_args()
    run = Path(args.run)
    units = {
        (d["document_id"], u["uid"]): u
        for d in _lines(run / "eval/fresh_units.jsonl")
        for u in d["units"]
    }
    j1, j2 = _judge(run / "eval/judge_j1.jsonl"), _judge(run / "eval/judge_j2.jsonl")
    ground = _grounding(run, args.batches)
    owner = json.loads(Path(args.owner).read_text()) if args.owner else {}
    oset = json.loads(Path(args.owner_set).read_text()) if args.owner_set else {"audit": []}
    to_bool = {"yes": True, "no": False, "unsure": False}

    audit_diff = [
        k
        for k in map(tuple, oset["audit"])
        if "|".join(k) in owner and to_bool[owner["|".join(k)]] != (j1[k]["verdict"] == "correct")
    ]
    ai_ok = len(audit_diff) < 2
    verdict, unresolved = {}, []
    for k in units:
        if "|".join(k) in owner:
            verdict[k] = to_bool[owner["|".join(k)]]
        elif j1[k]["verdict"] == j2[k]["verdict"] and ai_ok:
            verdict[k] = j1[k]["verdict"] == "correct"
        else:
            unresolved.append(k)

    def rel(u: dict) -> bool:
        return u["kind"] in ("relation", "causal_link")

    def is_candidate(k: tuple, u: dict) -> bool:
        if u["method"] == "v2":
            return rel(u) and k[0] not in set(args.v2_review)
        g = ground.get(k, {}).get("verdict")
        if g != "entailed":
            return False
        if u["kind"] == "causal_link":
            return u["desc"].endswith("[mechanism]") or u["desc"].endswith("[asserted]")
        if u["kind"] == "relation":
            return (
                "conditional" not in u["desc"]
                and "expected" not in u["desc"]
                and "NEGATED" not in u["desc"]
            )
        return False

    res = {"units": len(units), "audit_diff": len(audit_diff), "ai_consensus_usable": ai_ok}
    res["unresolved"] = ["|".join(k) for k in unresolved]
    for m in ("v2", "v3"):
        ks = [k for k, u in units.items() if u["method"] == m and rel(u) and k in verdict]
        res[f"{m}_relation_accuracy"] = f"{sum(verdict[k] for k in ks)}/{len(ks)}"
        cands = [k for k in ks if is_candidate(k, units[k])]
        res[f"{m}_expansion_candidates"] = len(cands)
        res[f"{m}_wrong_branches"] = sum(not verdict[k] for k in cands)
    v3_after = [
        k
        for k, u in units.items()
        if u["method"] == "v3"
        and rel(u)
        and k in verdict
        and ground.get(k, {}).get("verdict") == "entailed"
    ]
    res["v3_relation_accuracy_after_grounding"] = (
        f"{sum(verdict[k] for k in v3_after)}/{len(v3_after)}"
    )

    # 누락률: 맞는 관계 단위의 합집합(상대 방식이 그대로 담은 것은 한 번만) 대비 각 방식이 담은 비율
    def covered(k: tuple) -> str | None:
        c = {j1[k].get("covered_by_other"), j2[k].get("covered_by_other")}
        return "full" if c == {"full"} else None

    for scope, keep in (("relation", rel), ("meaning_unit", lambda u: True)):
        correct = [k for k, u in units.items() if keep(u) and verdict.get(k)]
        v2c = [k for k in correct if units[k]["method"] == "v2"]
        v3c = [k for k in correct if units[k]["method"] == "v3"]
        dup = sum(1 for k in v2c if covered(k) == "full")
        union = len(v2c) + len(v3c) - dup
        res[f"{scope}_union"] = union
        res[f"v2_{scope}_recall"] = f"{len(v2c)}/{union}"
        res[f"v3_{scope}_recall"] = f"{len(v3c)}/{union}"
    v3_units = [k for k, u in units.items() if u["method"] == "v3"]
    res["v3_units_partial_review"] = sum(
        1 for k in v3_units if ground.get(k, {}).get("verdict") == "partial"
    )
    res["v3_units_total"] = len(v3_units)
    res["v3_grounding"] = dict(Counter(ground[k]["verdict"] for k in v3_units if k in ground))
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

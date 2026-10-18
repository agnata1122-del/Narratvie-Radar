"""R1-X v3 출력의 형식 검증 (docs/EXPERIMENTS.md "R1-X").

v2는 기존 `nr classify ingest` 검증을 그대로 쓴다. v3는 운영 스키마가 없으므로 여기서
지침(guideline_v3.md)의 형식 규칙만 기계적으로 확인한다. 의미 판정은 하지 않는다.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

QTY = {
    "production_volume", "production_capacity", "supply", "demand", "price", "cost",
    "revenue", "profit", "margin", "investment", "market_share",
}  # fmt: skip
STATE = {"regulation", "business_status", "qualification", "contract", "shipment", "delivery"}
DIRECTIONS = {"qty": {"increase", "decrease", "unchanged"}, "state": {"start", "end", "complete"}}
MODALITY = {"actual", "expected", "conditional"}
ATTRIBUTION = {"author", "reported", "official"}
LEVELS = {"mechanism", "asserted", "speculative"}
PREDICATES = {"SUPPLIES_TO", "COMPETES_WITH", "PART_OF", "BELONGS_TO", "AFFECTS"}
POLARITY = {"enabler", "constraint", "neutral"}


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def check_doc(post: dict, out: dict) -> list[str]:
    errs = []
    text = (post.get("text") or "") + "\n" + (post.get("parent_text") or "")
    names = {e.get("name") for e in out.get("entities", [])}

    def verbatim(kind: str, i: int, ex: str | None) -> None:
        if not ex or ex not in text:
            errs.append(f"{kind}[{i}] excerpt not verbatim")
        elif len(ex) > 200:
            errs.append(f"{kind}[{i}] excerpt > 200")

    ids = set()
    for i, e in enumerate(out.get("events", [])):
        ids.add(e.get("id"))
        var = e.get("variable")
        kind = "qty" if var in QTY else "state" if var in STATE else None
        if kind is None:
            errs.append(f"event[{i}] variable {var!r}")
        elif e.get("direction") not in DIRECTIONS[kind]:
            errs.append(f"event[{i}] direction {e.get('direction')!r} for {var}")
        if e.get("modality") not in MODALITY:
            errs.append(f"event[{i}] modality {e.get('modality')!r}")
        if not isinstance(e.get("negated", False), bool):
            errs.append(f"event[{i}] negated not bool")
        if e.get("attribution") not in ATTRIBUTION:
            errs.append(f"event[{i}] attribution {e.get('attribution')!r}")
        if e.get("entity") not in names:
            errs.append(f"event[{i}] entity not in entities")
        if e.get("counterparty") and e["counterparty"] not in names:
            errs.append(f"event[{i}] counterparty not in entities")
        verbatim("event", i, e.get("excerpt"))
    for i, c in enumerate(out.get("causal_links", [])):
        if c.get("cause") not in ids or c.get("effect") not in ids:
            errs.append(f"causal_link[{i}] unknown event id")
        if c.get("evidence_level") not in LEVELS:
            errs.append(f"causal_link[{i}] evidence_level {c.get('evidence_level')!r}")
        if c.get("evidence_level") in {"mechanism", "asserted"} and not c.get("signal"):
            errs.append(f"causal_link[{i}] missing signal")
        verbatim("causal_link", i, c.get("excerpt"))
    for i, c in enumerate(out.get("claims", [])):
        if c.get("predicate") not in PREDICATES:
            errs.append(f"claim[{i}] predicate {c.get('predicate')!r}")
        if c.get("polarity") not in POLARITY:
            errs.append(f"claim[{i}] polarity {c.get('polarity')!r}")
        if c.get("subject") not in names or c.get("object") not in names:
            errs.append(f"claim[{i}] subject/object not in entities")
        verbatim("claim", i, c.get("excerpt"))
    return errs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_dirs", nargs="+")
    args = ap.parse_args()
    total = Counter()
    for d in map(Path, args.batch_dirs):
        posts = _records(d / "batch.jsonl")
        outs = _records(d / "out_v3.jsonl")
        if [p["document_id"] for p in posts] != [o["document_id"] for o in outs]:
            print(f"{d.name}: document order/count mismatch ({len(posts)} vs {len(outs)})")
            continue
        bad = 0
        for p, o in zip(posts, outs, strict=True):
            errs = check_doc(p, o["output"])
            bad += bool(errs)
            for e in errs:
                total[e.split(" ", 1)[1]] += 1
                print(f"{d.name} {p['document_id']}: {e}")
            out = o["output"]
            total["events"] += len(out.get("events", []))
            total["causal_links"] += len(out.get("causal_links", []))
            total["claims"] += len(out.get("claims", []))
        print(f"{d.name}: docs={len(posts)} docs_with_errors={bad}")
    print(json.dumps(dict(total), ensure_ascii=False))


if __name__ == "__main__":
    main()

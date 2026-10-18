"""E1 전체 분류 결과 집계와 평가 표본 준비 (docs/EXPERIMENTS.md E1).

- 대상 목록의 글마다 마지막 finance.v2 분류를 읽어 상태(accepted/review/error)를 센다.
- review 글은 N1·N2에서 뺀다. 뺀 건수를 사유별(모델 판단 / 자동 탐지 유형)로 센다.
- N1·N2 분석 가능 표본: accepted 글 중 메모리 관련 주장이 있는 글·주장 수.
- 배치 기록(ledger)과 토큰 기록을 합쳐 처리량·토큰·API 환산 비용을 낸다.
- 의미 정확성 평가용 무작위 50건(시드 고정)을 뽑아 원문·분류·빈 표시 칸을 쓴다.

이 스크립트는 효용을 판단하지 않는다. 사건·신호·순열 검정은 품질 확인 뒤 따로 한다.
"""

import argparse
import collections
import json
import random
import re
import sqlite3
from pathlib import Path

# 메모리 관련 주장: 주어나 목적어가 메모리 3사(D27) 또는 메모리 기술인 주장
MEMORY_KEYS = {"KR:000660", "KR:005930", "US:MU"}
MEMORY_TECH = re.compile(
    r"^TECH:.*(hbm|dram|ddr|nand|hbf|high-bandwidth-flash|socamm|lpcamm|memory)"
)
AUTO_FLAGS = (
    "상장사 식별자 오류",
    "미확인 티커",
    "subject 발췌 불일치",
    "object 발췌 불일치",
    "원문에 인과 표현 없음",
    "모회사 관계 근거 확인",
)
HAIKU_PRICE = {"input": 0.10, "output": 0.50}  # USD / 1M 토큰 (프롬프트 10만 이하)
OUT_TOKENS_PER_DOC = 250  # 출력 추정 (EXPERIMENTS 비용 추정과 같은 값)


def is_memory(key: str | None) -> bool:
    return bool(key) and (key in MEMORY_KEYS or bool(MEMORY_TECH.match(key)))


def memory_claims(output: dict) -> list[dict]:
    keys = {e.get("name"): e.get("canonical_key") for e in output.get("entities", [])}
    return [
        c
        for c in output.get("claims", [])
        if is_memory(keys.get(c.get("subject"))) or is_memory(keys.get(c.get("object")))
    ]


def reason_types(reason: str | None) -> set[str]:
    found = set()
    for part in (reason or "").split("; "):
        part = part.strip()
        if not part:
            continue
        auto = next((a for a in AUTO_FLAGS if part.startswith(a)), None)
        if auto:
            found.add(f"자동: {auto}")
        elif "상장사 식별자 확인" in part:
            found.add("모델: 상장사 식별자 확인 필요")
        else:
            found.add("모델: 기타(반어·모호한 지시 등)")
    return found or {"사유 없음"}


def load_runs(db: Path, ids: list[str]) -> dict[str, tuple]:
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT r.document_id, r.status, r.output, r.model, d.published_at, d.source "
        "FROM classification_runs r JOIN documents d USING (document_id) "
        "WHERE r.prompt_version LIKE '%finance.v2' AND r.model LIKE 'claude-haiku%' "
        "ORDER BY r.completed_at"
    ).fetchall()
    wanted = set(ids)
    latest = {}
    for doc, status, output, model, published, source in rows:
        if doc in wanted:
            latest[doc] = (status, json.loads(output) if output else {}, model, published, source)
    return latest


def summarize(args: argparse.Namespace) -> dict:
    ids = Path(args.ids).read_text().split()
    runs = load_runs(Path(args.db), ids)
    status = collections.Counter(r[0] for r in runs.values())

    excluded = collections.Counter()
    excluded_kind = collections.Counter()
    for status_, out, *_ in runs.values():
        if status_ != "review":
            continue
        types = reason_types(out.get("review_reason"))
        excluded.update(types)
        kinds = {t.split(":")[0] for t in types}
        kind = {frozenset({"모델"}): "모델만", frozenset({"자동"}): "자동만"}
        excluded_kind[kind.get(frozenset(kinds), "둘 다")] += 1

    n1_docs, n1_days, n2 = 0, set(), collections.Counter()
    review_mem_docs, predicates, noise = 0, collections.Counter(), 0
    for status_, out, _, published, _ in runs.values():
        if out.get("is_noise"):
            noise += 1
        mem = memory_claims(out)
        if status_ == "review":
            review_mem_docs += bool(mem)
            continue
        if status_ != "accepted":
            continue
        predicates.update(c.get("predicate") for c in out.get("claims", []))
        if mem:
            n1_docs += 1
            n1_days.add(published[:10])
            n2.update(c.get("stance") for c in mem)

    ledger = [json.loads(line) for line in Path(args.ledger).read_text().splitlines() if line]
    tokens = {
        t["batch"]: t
        for t in (json.loads(line) for line in Path(args.tokens).read_text().splitlines() if line)
    }
    batches = []
    for row in ledger:
        t = tokens.get(row["batch"], {})
        row = {**row, "agent_tokens": t.get("agent_tokens"), "agent_ms": t.get("agent_ms")}
        batches.append(row)
    total_tokens = sum(b["agent_tokens"] or 0 for b in batches)
    total_ms = sum(b["agent_ms"] or 0 for b in batches)
    docs = sum(b["in"] for b in batches)
    out_est = docs * OUT_TOKENS_PER_DOC
    cost = ((total_tokens - out_est) * HAIKU_PRICE["input"] + out_est * HAIKU_PRICE["output"]) / 1e6
    flag_types = collections.Counter()
    for b in batches:
        flag_types.update(b["flag_types"])

    return {
        "targets": len(ids),
        "classified": len(runs),
        "missing": len(ids) - len(runs),
        "status": dict(status),
        "noise_docs": noise,
        "review_excluded_from_n1_n2": status.get("review", 0),
        "review_excluded_by_reason_docs": dict(excluded.most_common()),
        "review_excluded_by_kind": dict(excluded_kind),
        "review_docs_with_memory_claims": review_mem_docs,
        "n1_eligible_docs": n1_docs,
        "n1_eligible_days": len(n1_days),
        "n2_memory_claims_by_stance": dict(n2),
        "n2_directional_claims": n2.get("positive", 0) + n2.get("negative", 0),
        "accepted_claims_by_predicate": dict(predicates.most_common()),
        "full_run": {
            "batches": len(batches),
            "docs": docs,
            "accepted": sum(b["accepted"] for b in batches),
            "review": sum(b["review"] for b in batches),
            "errors": sum(b["errors"] for b in batches),
            "auto_flag_types": dict(flag_types.most_common()),
            "agent_tokens_total": total_tokens,
            "agent_minutes_total": round(total_ms / 60000, 1),
            "docs_per_agent_minute": round(docs / (total_ms / 60000), 2) if total_ms else None,
            "api_equivalent_usd_estimate": round(cost, 2),
            "cost_note": (
                "에이전트 토큰 합계 중 글당 250토큰을 출력 단가로, 나머지를 입력 단가로 환산"
            ),
        },
        "batches": batches,
    }


def eval_sample(args: argparse.Namespace) -> list[dict]:
    ids = Path(args.ids).read_text().split()
    runs = load_runs(Path(args.db), ids)
    texts = {}
    for p in args.batch_files:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                texts[rec["document_id"]] = rec
    pool = sorted(runs)
    picked = sorted(random.Random(args.seed).sample(pool, args.n))
    out = []
    for i, doc in enumerate(picked, 1):
        status, output, model, published, source = runs[doc]
        rec = texts.get(doc, {})
        out.append(
            {
                "no": i,
                "document_id": doc,
                "source": source,
                "published_at": published,
                "status": status,
                "model": model,
                "text": rec.get("text"),
                "parent_text": rec.get("parent_text"),
                "output": output,
                # 소유자가 채운다: 1 맞음 / 0 틀림 / null 해당 없음
                "label_entities": None,
                "label_claims": None,
                "label_stance": None,
                "label_overall": None,
                "note": "",
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--ids", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary")
    s.add_argument("--ledger", required=True)
    s.add_argument("--tokens", required=True)
    e = sub.add_parser("sample")
    e.add_argument("--batch-files", nargs="+", required=True)
    e.add_argument("--seed", type=int, default=20261019)
    e.add_argument("--n", type=int, default=50)
    args = ap.parse_args()
    if args.cmd == "summary":
        print(json.dumps(summarize(args), ensure_ascii=False, indent=1))
    else:
        for rec in eval_sample(args):
            print(json.dumps(rec, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""E1 품질 검증 보조 자료 (docs/EXPERIMENTS.md E1). 판정 기준은 바꾸지 않는다.

claims : accepted 글의 주장에서 무작위 표본을 뽑아 주어·목적어·관계·인과 표시 칸을 만든다
         (기존 무작위 50건 평가와 별도. 70% 기준은 기존 50건에만 적용한다)
triage : review 글 중 메모리 관련 주장이 있는 글을 사유별로 나눠 우선 검토 목록을 만든다.
         식별자 사유는 "실제 식별자 오류"와 "탐지 규칙 오탐 가능(비상장 ORG·맞는 티커)"을 구분한다.
         판정은 사람이 한다. 관계를 지우거나 상태를 바꾸지 않는다.
"""

import argparse
import json
import random
from pathlib import Path

from summarize import load_runs, memory_claims

# 탐지 목록에 없지만 상장·주 시장을 알고 있는 티커 (작성자 지식 기준, 소유자 확인 필요)
KNOWN_TICKERS = {
    "US:CRSR": "Corsair Gaming, Nasdaq",
    "US:HPQ": "HP Inc., NYSE",
    "HK:0992": "Lenovo Group, HKEX",
    "US:BX": "Blackstone, NYSE",
    "JP:6758": "Sony Group, TSE",
    "HK:0981": "SMIC, HKEX (상하이 688981 겸상장)",
    "JP:285A": "Kioxia, TSE (2024-12 상장)",
    "TW:3260": "ADATA, TPEx",
}
# 상장사인데 키를 정하지 못한 경우 제안 키
LISTED_KEY_HINT = {"kioxia": "JP:285A", "adata": "TW:3260", "smic": "HK:0981", "asml": "NL:ASML"}
# 비상장이거나 상장 시점 확인이 필요한 회사: ORG: 키가 유효할 수 있다
PRIVATE_OR_PENDING = {
    "cxmt": "비상장(상하이 상장 추진 중, 글 시점 기준 상장 여부 확인 필요)",
    "ymtc": "비상장",
    "spacex": "비상장",
    "openai": "비상장",
}


def _identifier_verdict(part: str) -> tuple[str, str]:
    body = part.split(":", 1)[1].strip() if ":" in part else part
    name = body.split("(")[0].strip().lower()
    key = body[body.find("(") + 1 : body.rfind(")")] if "(" in body else ""
    if part.startswith("미확인 티커"):
        if key in KNOWN_TICKERS:
            return "탐지 오탐 가능: 맞는 티커", KNOWN_TICKERS[key]
        return "확인 필요: 티커", key
    if name in PRIVATE_OR_PENDING:
        return "탐지 오탐 가능: 비상장 ORG 유효", PRIVATE_OR_PENDING[name]
    if name in LISTED_KEY_HINT:
        return "실제 식별자 미지정: 상장사", f"제안 키 {LISTED_KEY_HINT[name]}"
    return "실제 식별자 오류", body


def triage(args: argparse.Namespace) -> list[dict]:
    ids = Path(args.ids).read_text().split()
    runs = load_runs(Path(args.db), ids)
    out = []
    for doc, (status, output, _, published, source) in sorted(runs.items()):
        if status != "review" or not memory_claims(output):
            continue
        items = []
        for part in (output.get("review_reason") or "").split("; "):
            part = part.strip()
            if not part:
                continue
            if part.startswith(("상장사 식별자", "미확인 티커")):
                verdict, note = _identifier_verdict(part)
            elif part.startswith(("subject 발췌", "object 발췌")):
                verdict, note = "사람 확인: 발췌 밖 주어·목적어(문맥 의존일 수 있음)", ""
            elif part.startswith("원문에 인과 표현 없음"):
                verdict, note = "사람 확인: 인과 근거", ""
            else:
                verdict, note = "사람 확인: 모델 표시", ""
            items.append({"reason": part, "verdict": verdict, "note": note})
        only_false_positive = bool(items) and all(
            i["verdict"].startswith("탐지 오탐") for i in items
        )
        out.append(
            {
                "document_id": doc,
                "source": source,
                "published_at": published,
                "reasons": items,
                "priority": "빠른 확인(식별자 오탐만)" if only_false_positive else "내용 검토",
                "memory_claims": memory_claims(output),
                # 소유자가 채운다: approve / keep_review / reject
                "decision": None,
                "note": "",
            }
        )
    return out


def claims_sample(args: argparse.Namespace) -> list[dict]:
    ids = Path(args.ids).read_text().split()
    runs = load_runs(Path(args.db), ids)
    texts = {}
    for p in args.batch_files:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                texts[rec["document_id"]] = rec
    pool = []
    for doc, (status, output, _, published, source) in sorted(runs.items()):
        if status != "accepted":
            continue
        mem = memory_claims(output)
        for i, claim in enumerate(output.get("claims", [])):
            pool.append((doc, i, claim, claim in mem, published, source, output))
    picked = sorted(
        random.Random(args.seed).sample(pool, min(args.n, len(pool))), key=lambda p: p[:2]
    )
    out = []
    for n, (doc, i, claim, is_mem, published, source, output) in enumerate(picked, 1):
        rec = texts.get(doc, {})
        out.append(
            {
                "no": n,
                "document_id": doc,
                "claim_index": i,
                "source": source,
                "published_at": published,
                "memory_claim": is_mem,
                "text": rec.get("text"),
                "parent_text": rec.get("parent_text"),
                "entities": output.get("entities", []),
                "claim": claim,
                # 소유자가 채운다: 1 맞음 / 0 틀림 / null 해당 없음
                "label_subject": None,
                "label_object": None,
                "label_predicate": None,
                "label_causal": None,  # 원문이 방향·인과를 말하는가 (AFFECTS·CLAIMED_CAUSE_OF)
                "label_stance": None,
                "note": "",
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--ids", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("claims")
    c.add_argument("--batch-files", nargs="+", required=True)
    c.add_argument("--seed", type=int, default=20261020)
    c.add_argument("--n", type=int, default=50)
    sub.add_parser("triage")
    args = ap.parse_args()
    rows = claims_sample(args) if args.cmd == "claims" else triage(args)
    for rec in rows:
        print(json.dumps(rec, ensure_ascii=False))


if __name__ == "__main__":
    main()

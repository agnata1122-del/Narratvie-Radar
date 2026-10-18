"""E1 전체 분류 배치 준비·후처리 (docs/EXPERIMENTS.md E1).

    prep  : 남은 대상(대상 목록 − 이미 분류한 파일럿)을 목록 순서대로 50건씩 나눠 배치 폴더를 만든다
    flag  : 모델 출력에 자동 탐지 규칙을 적용해 의심 글을 review로 표시한다 (내용은 지우지 않는다)
    ledger: 배치별 기록(ingest 결과·탐지 사유·토큰·시간)을 한 줄씩 쌓는다

탐지 규칙은 관계를 지우지 않고 `needs_review`와 `review_reason`만 더한다. 사람이 승인하기
전까지 review 글은 N1·N2에서 뺀다.
"""

import argparse
import json
import re
from pathlib import Path

from narrative_radar.normalization.text import normalize_text

BATCH = 50

# 확인한 표준 식별자: 기준 스냅숏 온톨로지의 키 + 주 상장 시장을 확인한 티커.
# 여기에 없는 국가:티커 키는 "미확인 티커"로 검토에 넘긴다.
VERIFIED_TICKERS = {
    "US:NVDA", "US:MU", "US:AMD", "US:INTC", "US:AAPL", "KR:000660", "KR:005930",
    "TW:2330", "TW:2303", "TW:2357", "US:MSFT", "US:AVGO", "US:QCOM", "US:GFS",
    "US:AMZN", "US:GOOGL", "US:META", "US:TSLA", "US:ORCL", "US:CRWV", "US:ARM",
    "US:SMCI", "US:DELL", "US:HPE", "US:IBM", "US:CSCO", "US:TXN", "US:WDC", "US:STX",
}  # fmt: skip
# 상장사인데 ORG: 키로 오면 식별자 오류로 본다 (이름 → 표준 키)
LISTED_NAMES = {
    "microsoft": "US:MSFT", "broadcom": "US:AVGO", "qualcomm": "US:QCOM", "amazon": "US:AMZN",
    "apple": "US:AAPL", "intel": "US:INTC", "amd": "US:AMD", "meta": "US:META",
    "tesla": "US:TSLA", "oracle": "US:ORCL", "coreweave": "US:CRWV", "nvidia": "US:NVDA",
    "micron": "US:MU", "tsmc": "TW:2330", "samsung": "KR:005930", "sk hynix": "KR:000660",
    "hynix": "KR:000660", "globalfoundries": "US:GFS", "umc": "TW:2303", "asus": "TW:2357",
    "asml": None, "smic": None, "cxmt": None, "adata": None, "arm": "US:ARM",
}  # fmt: skip
# 자회사·사업부 ↔ 모회사. 이 둘을 잇는 관계는 근거를 사람이 확인한다
PARENT_OF = {"ORG:google": "US:GOOGL", "ORG:aws": "US:AMZN", "ORG:youtube": "US:GOOGL"}
CAUSAL_MARKERS = re.compile(
    r"because|due to|caus|lead(s)? to|led to|result|driv|thanks to|so that|therefore|thus|"
    r"as a result|owing to|since |때문|로 인해|탓|덕분|결과|그래서|따라서",
    re.IGNORECASE,
)


def _mentions(name: str, excerpt: str) -> bool:
    n, e = normalize_text(name), normalize_text(excerpt)
    if n in e:
        return True
    # 여러 단어 이름은 가장 긴 단어만 있어도 언급으로 본다 (예: "SK hynix" → "hynix")
    words = [w for w in re.split(r"[\s\-/]+", n) if len(w) >= 3]
    return bool(words) and max(words, key=len) in e


def flags_for(output: dict) -> list[str]:
    found: list[str] = []
    keys = {}
    for e in output.get("entities", []):
        k, name = e.get("canonical_key"), e.get("name", "")
        keys[name] = k
        low = normalize_text(name)
        if k and k.startswith("ORG:") and low in LISTED_NAMES:
            found.append(f"상장사 식별자 오류: {name}({k})")
        if k and re.fullmatch(r"[A-Z]{2}:[A-Z0-9.\-]+", k) and k not in VERIFIED_TICKERS:
            found.append(f"미확인 티커: {name}({k})")
    for c in output.get("claims", []):
        excerpt = c.get("excerpt", "")
        for role in ("subject", "object"):
            if not _mentions(c.get(role, ""), excerpt):
                found.append(f"{role} 발췌 불일치: {c.get(role)}")
        if c.get("predicate") == "CLAIMED_CAUSE_OF" and not CAUSAL_MARKERS.search(excerpt):
            found.append(f"원문에 인과 표현 없음: {c.get('subject')}→{c.get('object')}")
        pair = {keys.get(c.get("subject")), keys.get(c.get("object"))}
        if any(sub in pair and parent in pair for sub, parent in PARENT_OF.items()):
            found.append(f"모회사 관계 근거 확인: {c.get('subject')}–{c.get('object')}")
    return sorted(set(found))


def cmd_prep(args: argparse.Namespace) -> None:
    ids = Path(args.ids).read_text().split()
    done = set()
    for p in args.done:
        done |= set(Path(p).read_text().split())
    rest = [i for i in ids if i not in done]
    for n in range(0, len(rest), BATCH):
        d = Path(args.out) / f"b{n // BATCH + 1:02d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "ids.txt").write_text("".join(f"{i}\n" for i in rest[n : n + BATCH]))
    print(f"remaining={len(rest)} batches={-(-len(rest) // BATCH)}")


def cmd_flag(args: argparse.Namespace) -> None:
    d = Path(args.batch)
    rows, flagged = [], {}
    for line in (d / "out.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out = rec["output"]
        found = flags_for(out)
        if found:
            flagged[rec["document_id"]] = found
            out["needs_review"] = True
            reason = "; ".join(found)
            out["review_reason"] = (
                f"{out['review_reason']}; {reason}" if out.get("review_reason") else reason
            )[:500]
        rows.append(rec)
    with (d / "out_flagged.jsonl").open("w", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (d / "flags.json").write_text(json.dumps(flagged, ensure_ascii=False, indent=1))
    print(f"lines={len(rows)} flagged_docs={len(flagged)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep")
    p.add_argument("--ids", required=True)
    p.add_argument("--done", nargs="*", default=[])
    p.add_argument("--out", required=True)
    f = sub.add_parser("flag")
    f.add_argument("batch")
    args = ap.parse_args()
    {"prep": cmd_prep, "flag": cmd_flag}[args.cmd](args)


if __name__ == "__main__":
    main()

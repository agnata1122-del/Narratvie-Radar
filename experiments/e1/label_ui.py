"""E1 소유자 판정 입력 화면 (docs/EXPERIMENTS.md E1 · R0).

    build : 판정 스키마(label_schema.json) + 표본 jsonl + 한국어 시트(md)로 HTML 한 장을 만든다.
            판정 칸은 스키마에서 만든다(시트마다 고정 문구를 두지 않는다).
    apply : 화면에서 내보낸 JSON을 검증해 표본 jsonl의 판정 칸에 옮겨 쓴다(새 파일로).

HTML에는 수집 원문 번역이 들어가므로 공개 저장소에 두지 않는다.
출력은 작업 폴더나 비공개 저장소에만 둔다.
"""

import argparse
import json
import re
from pathlib import Path

HEADINGS = {
    "number": re.compile(r"^## (\d+)\.", re.M),
    "doc_id": re.compile(r"^### .*`(doc_[0-9A-Z]+)`", re.M),
}


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sections(md: str, kind: str) -> tuple[str, dict[str, str]]:
    """시트 md를 항목별 조각으로 나눈다. 키는 번호(문자열) 또는 document_id."""
    pat = HEADINGS[kind]
    marks = list(pat.finditer(md))
    intro = md[: marks[0].start()] if marks else md
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        body = md[m.start() : end]
        # 화면이 판정 칸을 만들므로 시트의 체크박스 줄은 뺀다
        body = "\n".join(
            ln for ln in body.splitlines() if not re.match(r"^- (표시|판정):", ln.strip())
        )
        out[m.group(1)] = body.strip()
    return intro.strip(), out


def _item_key(rec: dict, key: list[str]) -> str:
    return "|".join(str(rec.get(k)) for k in key)


def cmd_build(args: argparse.Namespace) -> None:
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    data_dir = Path(args.data)
    originals = {}
    for p in args.batch_files:
        for rec in _records(Path(p)):
            originals[rec["document_id"]] = rec
    tails = {}
    if args.tails:
        tmd = Path(args.tails).read_text(encoding="utf-8")
        marks = list(re.finditer(r"^## (eval|claims|review) (\S+)\s*$", tmd, re.M))
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(tmd)
            tails[(m.group(1), m.group(2))] = tmd[m.end() : end].strip()
    payload = {"version": schema["version"], "sheets": []}
    for name, md_paths in (
        ("eval", args.eval_md),
        ("claims", args.claims_md),
        ("review", args.review_md),
    ):
        if not md_paths:
            continue
        spec = schema["sheets"][name]
        md = "\n\n".join(Path(p).read_text(encoding="utf-8") for p in md_paths)
        intro, parts = _sections(md, spec["section"])
        items = []
        for rec in _records(data_dir / spec["source"]):
            src = originals.get(rec["document_id"], rec)
            sec_key = str(rec["no"]) if spec["section"] == "number" else rec["document_id"]
            items.append(
                {
                    "key": _item_key(rec, spec["key"]),
                    "ids": {k: rec.get(k) for k in spec["key"]},
                    "text": parts.get(sec_key, "(번역 없음)")
                    + (
                        f"\n\n원문 번역 (이어서):\n{tails[(name, sec_key)]}"
                        if (name, sec_key) in tails
                        else ""
                    ),
                    "group": rec.get("group"),
                    # 번역 시트는 1,500자에서 잘린다. 판단할 때 원문 전체를 펼쳐 볼 수 있게 둔다
                    "original": "\n\n".join(
                        t for t in (src.get("parent_text"), src.get("text")) if t
                    ),
                }
            )
        missing = sum(1 for it in items if it["text"].startswith("(번역 없음)"))
        print(f"{name}: items={len(items)} missing_translation={missing}")
        payload["sheets"].append({"name": name, "spec": spec, "intro": intro, "items": items})
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    Path(args.out).write_text(
        TEMPLATE_PATH.read_text(encoding="utf-8").replace("__DATA__", data), encoding="utf-8"
    )
    print(f"wrote {args.out}")


def cmd_apply(args: argparse.Namespace) -> None:
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    exported = json.loads(Path(args.export).read_text(encoding="utf-8"))
    if exported.get("version") != schema["version"]:
        raise SystemExit("schema version mismatch")
    data_dir, out_dir = Path(args.data), Path(args.out)
    for name, entries in exported["sheets"].items():
        spec = schema["sheets"][name]
        allowed = {f["name"]: [o[0] for o in f["options"]] for f in spec["fields"]}
        by_key = {e["key"]: e for e in entries}
        recs = _records(data_dir / spec["source"])
        filled = 0
        for rec in recs:
            e = by_key.get(_item_key(rec, spec["key"]))
            if not e:
                continue
            for field, value in e.get("labels", {}).items():
                if field not in allowed or value not in allowed[field]:
                    raise SystemExit(f"{name} {e['key']}: invalid {field}={value!r}")
                rec[field] = value
            rec[spec["note"]] = e.get("note", "")
            filled += 1
        target = out_dir / spec["source"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8"
        )
        print(f"{name}: filled={filled}/{len(recs)} -> {target}")


TEMPLATE_PATH = Path(__file__).with_name("label_ui.html")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default=str(Path(__file__).with_name("label_schema.json")))
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--data", required=True, help="데이터 저장소의 experiments/e1")
    b.add_argument("--eval-md", nargs="*", default=[])
    b.add_argument("--claims-md", nargs="*", default=[])
    b.add_argument("--review-md", nargs="*", default=[])
    b.add_argument("--tails", help="1,500자 뒤 번역 (## eval 3 형식)")
    b.add_argument("--batch-files", nargs="*", default=[], help="원문 전체가 든 batch.jsonl")
    b.add_argument("--out", required=True)
    a = sub.add_parser("apply")
    a.add_argument("--data", required=True)
    a.add_argument("--export", required=True)
    a.add_argument("--out", required=True, help="판정을 채운 jsonl을 쓸 폴더")
    args = ap.parse_args()
    {"build": cmd_build, "apply": cmd_apply}[args.cmd](args)


if __name__ == "__main__":
    main()

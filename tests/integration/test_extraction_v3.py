"""추출 규약 v3 저장·반영 (DECISIONS D38).

글과 추출 결과는 규칙 확인용으로 직접 만든 최소 예시다 (DECISIONS D0 예외).
"""

import json

import sqlalchemy as sa
from graphkit import HBM, NV, SKH

from narrative_radar.classifiers.session import (
    EXTRACTION_VERSION,
    export_batch,
    ingest_extractions,
    prompt_version_for,
)
from narrative_radar.db.models import Claim, ClassificationRun
from narrative_radar.domains import get_pack
from narrative_radar.schemas import extraction
from narrative_radar.schemas.enums import ClassificationStatus, EdgeType

TEXT = "HBM lines took capacity so DDR supply fell, and SK hynix ships HBM to NVIDIA"
DDR = ("DDR", "technology", "TECH:ddr")
PV = prompt_version_for(get_pack("finance"), "v3")


def _entities(*items):
    return [{"name": n, "type": t, "canonical_key": k} for n, t, k in items]


def _output(**over):
    out = {
        "relevance": 0.9,
        "is_noise": False,
        "entities": _entities(HBM, DDR, SKH, NV),
        "stance": "neutral",
        "events": [
            {"id": "e1", "entity": "HBM", "variable": "production_capacity",
             "direction": "increase", "modality": "actual", "attribution": "author",
             "excerpt": "HBM lines took capacity"},
            {"id": "e2", "entity": "DDR", "variable": "supply", "direction": "decrease",
             "modality": "actual", "attribution": "author", "excerpt": "DDR supply fell"},
        ],
        "causal_links": [
            {"cause": "e1", "effect": "e2", "evidence_level": "asserted", "signal": "so",
             "excerpt": "HBM lines took capacity so DDR supply fell"},
        ],
        "claims": [
            {"subject": "SK hynix", "predicate": "SUPPLIES_TO", "object": "NVIDIA",
             "polarity": "enabler", "modality": "actual", "attribution": "author",
             "excerpt": "SK hynix ships HBM to NVIDIA"},
        ],
        "needs_review": False,
    }  # fmt: skip
    return out | over


def _verdicts(link="entailed", claim="entailed", events=("entailed", "entailed")):
    vs = [{"kind": "event", "index": i, "verdict": v} for i, v in enumerate(events)]
    vs.append({"kind": "causal_link", "index": 0, "verdict": link})
    vs.append({"kind": "claim", "index": 0, "verdict": claim})
    return vs


def _ingest(g, doc, output=None, verdicts=None):
    line = json.dumps(
        {
            "document_id": doc.document_id,
            "content_hash": doc.content_hash,
            "output": output or _output(),
        }
    )
    ground = json.dumps({"document_id": doc.document_id, "verdicts": verdicts or _verdicts()})
    return ingest_extractions(g.session, g.clock, [line], [ground], "test-model", g.cls_run, PV)


def test_entailed_items_become_edges(g):
    doc = g.doc(TEXT)
    report = _ingest(g, doc)
    assert (report.accepted, report.errors) == (1, [])
    run = g.session.scalars(sa.select(ClassificationRun)).one()
    assert run.schema_version == extraction.SCHEMA_VERSION
    assert run.prompt_version.startswith(EXTRACTION_VERSION + "+")
    assert run.output["grounding"][0]["verdict"] == "entailed"
    g.build()
    assert g.edge("TECH:hbm", "TECH:ddr") is not None  # 인과 연결 → AFFECTS
    assert g.edge("KR:000660", "US:NVDA", EdgeType.SUPPLIES_TO) is not None
    stored = g.session.scalars(sa.select(Claim).order_by(Claim.predicate)).all()
    assert {c.evidence_status.value for c in stored} == {"community_opinion"}
    assert {c.stance.value for c in stored} == {"neutral"}  # 주장별 태도는 쓰지 않는다 (D35)


def test_partial_or_speculative_items_are_not_applied(g):
    doc = g.doc(TEXT)
    out = _output()
    out["causal_links"][0]["evidence_level"] = "speculative"
    _ingest(g, doc, out, _verdicts(claim="partial"))
    g.build()
    assert g.node("TECH:ddr") is not None  # 개체는 남는다
    assert g.edge("TECH:hbm", "TECH:ddr") is None
    assert g.edge("KR:000660", "US:NVDA", EdgeType.SUPPLIES_TO) is None


def test_planned_or_negated_claims_are_not_applied(g):
    doc = g.doc(TEXT)
    out = _output()
    out["claims"][0]["modality"] = "expected"
    _ingest(g, doc, out)
    g.build()
    assert g.edge("KR:000660", "US:NVDA", EdgeType.SUPPLIES_TO) is None


def test_missing_or_incomplete_grounding_is_an_error(g):
    doc = g.doc(TEXT)
    line = json.dumps(
        {"document_id": doc.document_id, "content_hash": doc.content_hash, "output": _output()}
    )
    r = ingest_extractions(g.session, g.clock, [line], [], "m", g.cls_run, PV)
    assert r.accepted == 0 and "no grounding verdicts" in r.errors[0]
    r = _ingest(g, g.doc(TEXT), verdicts=_verdicts()[:-1])
    assert r.accepted == 0 and "exactly once" in r.errors[0]


def test_structural_rules(g):
    doc = g.doc(TEXT)
    out = _output()
    out["events"][0]["excerpt"] = "not in the post"
    out["events"][1]["direction"] = "start"  # 양 변수에 상태 방향
    out["claims"][0]["predicate"] = "RELATED_TO"
    r = _ingest(g, doc, out)
    msg = r.errors[0]
    assert "not verbatim" in msg and "does not fit" in msg and "not used in v3" in msg
    status = g.session.scalars(sa.select(ClassificationRun.status)).one()
    assert status == ClassificationStatus.ERROR


def test_model_written_grounding_is_rejected(g):
    out = _output(grounding=_verdicts())
    r = _ingest(g, g.doc(TEXT), out)
    assert "grounding must come from the grounding file" in r.errors[0]


def test_v3_is_preferred_and_export_skips_done(g, tmp_path):
    doc = g.doc(TEXT)
    pack = get_pack("finance")
    _, ctx, n = export_batch(g.session, g.clock, 10, tmp_path, pack, schema="v3")
    assert n == 1
    context = json.loads(ctx.read_text())
    assert context["schema_version"] == extraction.SCHEMA_VERSION
    assert context["guidelines"][0].endswith("extraction_v3.md")
    # v2 분류가 먼저 있어도 v3가 우선 반영된다
    g.classify(doc, [HBM, DDR], [("HBM", "RELATED_TO", "DDR", {})])
    _ingest(g, doc)
    g.build()
    assert g.edge("TECH:hbm", "TECH:ddr", EdgeType.RELATED_TO) is None
    assert g.edge("TECH:hbm", "TECH:ddr") is not None
    _, _, n = export_batch(g.session, g.clock, 10, tmp_path, pack, schema="v3")
    assert n == 0

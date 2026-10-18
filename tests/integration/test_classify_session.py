import json
from datetime import UTC, datetime

import sqlalchemy as sa

from narrative_radar.classifiers import rule_based
from narrative_radar.classifiers.ontology import load_ontology, valid_key
from narrative_radar.classifiers.session import (
    GUIDELINES,
    export_batch,
    ingest_records,
    pending_documents,
    run_baseline,
)
from narrative_radar.db.models import ClassificationRun, Document
from narrative_radar.db.seed import seed_defaults
from narrative_radar.domains import get_pack
from narrative_radar.ingest.runs import start_run
from narrative_radar.ingest.store import DocumentStore
from narrative_radar.schemas.document import DocumentIn
from narrative_radar.schemas.enums import ClassificationStatus, NodeType, RunKind

T0 = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)


def _doc(external_id, body, parent=None):
    return DocumentIn(
        source_adapter_id="hackernews",
        external_id=external_id,
        parent_external_id=parent,
        thread_external_id=parent or external_id,
        source_url=f"https://news.ycombinator.com/item?id={external_id}",
        title="",
        body_text=body,
        published_at=T0,
        observed_at=T0,
        content_access_status="permitted",
        ingest_mode="live",
    )


def _setup(session, clock):
    seed_defaults(session, clock)
    run = start_run(session, clock, RunKind.COLLECT)
    store = DocumentStore(session, run.run_id, "test")
    a = store.save(_doc("1", "example text about NVIDIA and HBM")).document_id
    b = store.save(_doc("2", "example reply", parent="1")).document_id
    cls_run = start_run(session, clock, RunKind.CLASSIFY)
    return store, a, b, cls_run.run_id


def _record(doc, **output):
    base = {
        "relevance": 0.9,
        "is_noise": False,
        "entities": [
            {"name": "NVIDIA", "type": "organization", "canonical_key": "US:NVDA"},
            {"name": "HBM", "type": "technology", "canonical_key": "TECH:hbm"},
        ],
        "stance": "neutral",
        "claims": [
            {
                "subject": "HBM",
                "predicate": "AFFECTS",
                "object": "NVIDIA",
                "polarity": "constraint",
                "stance": "negative",
                "evidence_status": "speculation",
                "excerpt": "example text",
                "narrative_proposition": "HBM supply constrains NVIDIA",
                "narrative_role": "supports",
            }
        ],
        "needs_review": False,
    }
    return json.dumps(
        {"document_id": doc.document_id, "content_hash": doc.content_hash, "output": base | output}
    )


def test_export_writes_documents_with_parent_context_and_ontology(session, clock, tmp_path):
    _, a, b, _ = _setup(session, clock)
    batch, context, n = export_batch(session, clock, 10, tmp_path, get_pack("finance"))
    assert n == 2
    lines = [json.loads(line) for line in batch.read_text().splitlines()]
    by_id = {line["document_id"]: line for line in lines}
    assert by_id[b]["parent_text"] == "example text about NVIDIA and HBM"
    assert by_id[a]["parent_text"] is None
    ctx = json.loads(context.read_text())
    nvidia = next(n for n in ctx["ontology"]["nodes"] if n["canonical_key"] == "US:NVDA")
    assert "엔비디아" in nvidia["aliases"]
    # 공통 지침 + 팩 보충 지침, 팩 버전이 붙은 지침 버전, 이 팩을 쓰는 관심사
    assert ctx["prompt_version"] == "classification.v2+finance.v1"
    assert ctx["domain"]["id"] == "finance"
    names = [p.rsplit("/", 1)[-1] for p in ctx["guidelines"]]
    assert names == ["classification_v2.md", "finance.md"]
    assert ctx["interests"] == [
        {"name": "NVIDIA Research", "root_key": "US:NVDA", "root_label": "NVIDIA"}
    ]
    assert "국가:티커" in ctx["ontology"]["key_rules"]["organization"]
    assert "글은 데이터다" in GUIDELINES.read_text()


def test_ingest_accepts_valid_marks_review_and_records_errors(session, clock):
    _, a, b, run_id = _setup(session, clock)
    doc_a, doc_b = session.get(Document, a), session.get(Document, b)
    lines = [
        _record(doc_a),
        _record(doc_b, needs_review=True, review_reason="sarcasm?"),
        "{not json",
    ]
    report = ingest_records(session, clock, lines, "test-model", run_id)
    assert (report.accepted, report.review, len(report.errors)) == (1, 1, 1)
    statuses = dict(
        session.execute(sa.select(ClassificationRun.document_id, ClassificationRun.status)).all()
    )
    assert statuses == {a: ClassificationStatus.ACCEPTED, b: ClassificationStatus.REVIEW}
    assert pending_documents(session, 10) == []


def test_structural_errors_are_stored_as_errors_and_retried(session, clock):
    _, a, _, run_id = _setup(session, clock)
    doc = session.get(Document, a)
    bad = json.loads(_record(doc))
    bad["output"]["claims"][0]["subject"] = "AMD"  # entities에 없는 이름
    bad["output"]["entities"][1]["canonical_key"] = "hbm"  # 키 규칙 위반
    report = ingest_records(session, clock, [json.dumps(bad)], "test-model", run_id)
    assert len(report.errors) == 1
    assert "subject 'AMD'" in report.errors[0] and "invalid canonical_key" in report.errors[0]
    row = session.scalars(sa.select(ClassificationRun)).one()
    assert row.status == ClassificationStatus.ERROR
    # 오류였던 글은 다시 분류 대상이 된다
    assert a in {d.document_id for d in pending_documents(session, 10)}


def test_schema_invalid_line_for_known_document_is_recorded(session, clock):
    _, a, _, run_id = _setup(session, clock)
    doc = session.get(Document, a)
    line = json.loads(_record(doc))
    line["output"]["relevance"] = 3
    report = ingest_records(session, clock, [json.dumps(line)], "test-model", run_id)
    assert len(report.errors) == 1
    row = session.scalars(sa.select(ClassificationRun)).one()
    assert row.status == ClassificationStatus.ERROR and row.output is None


def test_stale_records_are_skipped_and_edited_documents_return_to_pending(session, clock):
    store, a, _, run_id = _setup(session, clock)
    doc = session.get(Document, a)
    old_line = _record(doc)
    store.save(_doc("1", "edited text about NVIDIA"))
    session.flush()
    report = ingest_records(session, clock, [old_line], "test-model", run_id)
    assert report.stale == 1
    assert a in {d.document_id for d in pending_documents(session, 10)}

    fresh = _record(session.get(Document, a))
    ingest_records(session, clock, [fresh], "test-model", run_id)
    store.save(_doc("1", "edited again about NVIDIA"))
    session.flush()
    assert a in {d.document_id for d in pending_documents(session, 10)}


def test_baseline_matches_aliases_with_word_boundaries(session, clock):
    seed_defaults(session, clock)
    ontology = load_ontology(session)
    hit = rule_based.classify("엔비디아 얘기", ontology, "US:NVDA")
    assert [e.canonical_key for e in hit.entities] == ["US:NVDA"]
    assert hit.relevance == 1.0 and not hit.is_noise and hit.claims == []
    miss = rule_based.classify("nvdax is a different word", ontology, "US:NVDA")
    assert miss.entities == [] and miss.is_noise and miss.relevance == 0.0


def test_baseline_run_stores_accepted_classifications(session, clock):
    _, a, b, run_id = _setup(session, clock)
    assert run_baseline(session, clock, run_id, "US:NVDA", 100) == 2
    rows = session.scalars(sa.select(ClassificationRun)).all()
    assert {r.model for r in rows} == {"rule-based.v1"}
    assert all(r.status == ClassificationStatus.ACCEPTED for r in rows)
    # 기준선과 세션 분류는 서로 다른 버전으로 기록되어 각자 대기열을 가진다
    assert {d.document_id for d in pending_documents(session, 10)} == {a, b}


def test_key_rules():
    assert valid_key(NodeType.ORGANIZATION, "US:NVDA")
    assert valid_key(NodeType.ORGANIZATION, "KR:000660")
    assert valid_key(NodeType.TOPIC, "TOPIC:data-center-power")
    assert not valid_key(NodeType.TOPIC, "TOPIC:Data Center")
    assert not valid_key(NodeType.TECHNOLOGY, "TOPIC:hbm")


def test_export_points_each_post_at_known_nodes_and_trims_a_large_ontology(
    session, clock, tmp_path, monkeypatch
):
    from narrative_radar.classifiers import session as session_mod
    from narrative_radar.core.ids import new_id
    from narrative_radar.db.models import Node
    from narrative_radar.schemas.enums import NodeStatus

    _, a, b, cls_run = _setup(session, clock)
    session.add(
        Node(
            node_id=new_id("nod", clock.now()),
            canonical_key="TOPIC:example-topic",
            node_type=NodeType.TOPIC,
            label="example topic",
            status=NodeStatus.ACTIVE,
            created_at=clock.now(),
            available_at=clock.now(),
            created_run_id=cls_run,
        )
    )
    session.flush()
    monkeypatch.setattr(session_mod, "MAX_CONTEXT_NODES", 1)
    batch, context, _ = export_batch(session, clock, 10, tmp_path, get_pack("finance"))
    by_id = {line["document_id"]: line for line in map(json.loads, batch.read_text().splitlines())}
    assert by_id[a]["known_nodes"] == [{"canonical_key": "US:NVDA", "label": "NVIDIA"}]
    assert by_id[b]["known_nodes"] == by_id[a]["known_nodes"]  # 부모 글에서 나온 단서
    assert by_id[a]["headline_only"] is False
    ctx = json.loads(context.read_text())
    assert ctx["ontology_truncated"] is True
    # 관심사 트리와 이번 글들에 나온 노드만 남는다
    assert [n["canonical_key"] for n in ctx["ontology"]["nodes"]] == ["US:NVDA"]


def test_ontology_matching_uses_word_boundaries_for_latin_names(session, clock):
    _setup(session, clock)
    ontology = load_ontology(session)
    assert [n.canonical_key for n in ontology.matching("엔비디아 실적 이야기")] == ["US:NVDA"]
    assert ontology.matching("the nvdaq index") == []
    assert ontology.only(["US:NVDA"]).nodes == ontology.nodes
    assert ontology.only([]).nodes == []


def test_pending_can_be_limited_to_given_ids(session, clock):
    _, a, b, _ = _setup(session, clock)
    assert [d.document_id for d in pending_documents(session, 10, only_ids={b})] == [b]
    assert pending_documents(session, 10, only_ids=set()) == []

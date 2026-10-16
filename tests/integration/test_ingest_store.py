from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from narrative_radar.db.models import (
    Claim,
    ClassificationRun,
    Document,
    DocumentComment,
    DocumentMetricSnapshot,
    RawDocument,
    SourceHealth,
)
from narrative_radar.db.seed import seed_defaults
from narrative_radar.ingest.health import record_health
from narrative_radar.ingest.runs import finish_run, start_run
from narrative_radar.ingest.store import DocumentStore
from narrative_radar.schemas.document import CommentIn, DocumentIn, MetricsIn
from narrative_radar.schemas.enums import (
    ClassificationStatus,
    EdgeType,
    EvidenceStatus,
    Polarity,
    RunKind,
    RunStatus,
    SourceHealthStatus,
    Stance,
)

T0 = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)


def _doc(external_id="100", body="body", observed=T0, metrics=None, **kw) -> DocumentIn:
    fields = {
        "source_adapter_id": "hackernews",
        "external_id": external_id,
        "source_url": f"https://news.ycombinator.com/item?id={external_id}",
        "title": "NVIDIA earnings thread",
        "body_text": body,
        "author_hash": "a" * 64,
        "published_at": T0 - timedelta(minutes=5),
        "observed_at": observed,
        "content_access_status": "permitted",
        "ingest_mode": "live",
        "metrics": metrics,
    }
    return DocumentIn(**(fields | kw))


def _store(session, clock) -> DocumentStore:
    seed_defaults(session, clock)
    run = start_run(session, clock, RunKind.COLLECT)
    return DocumentStore(session, run.run_id, parser_version="test.v1")


def test_same_item_twice_is_one_document_with_two_metric_snapshots(session, clock):
    store = _store(session, clock)
    first = store.save(_doc(metrics=MetricsIn(comment_count=3, upvote_count=10)))
    second = store.save(
        _doc(
            observed=T0 + timedelta(minutes=10), metrics=MetricsIn(comment_count=8, upvote_count=25)
        )
    )
    assert first.created and not second.created
    assert first.document_id == second.document_id
    assert not second.content_changed
    assert session.scalar(sa.select(sa.func.count()).select_from(Document)) == 1
    counts = session.scalars(
        sa.select(DocumentMetricSnapshot.comment_count).order_by(DocumentMetricSnapshot.observed_at)
    ).all()
    # 댓글 수는 합치지 않고 관측 시각별 값으로 남는다
    assert counts == [3, 8]


def test_same_snapshot_time_is_not_duplicated(session, clock):
    store = _store(session, clock)
    store.save(_doc(metrics=MetricsIn(comment_count=3)))
    assert store.save(_doc(metrics=MetricsIn(comment_count=3))).snapshot_added is False
    assert store.add_metrics("hackernews", "100", T0, MetricsIn(comment_count=3)) is False
    assert store.add_metrics(
        "hackernews", "100", T0 + timedelta(hours=1), MetricsIn(comment_count=9)
    )
    assert session.scalar(sa.select(sa.func.count()).select_from(DocumentMetricSnapshot)) == 2


def test_edited_content_replaces_text_and_requests_reanalysis(session, clock):
    store = _store(session, clock)
    doc_id = store.save(_doc(body="original")).document_id
    doc = session.get(Document, doc_id)
    doc.processed_at = T0
    session.flush()

    result = store.save(_doc(body="edited", observed=T0 + timedelta(minutes=30)))
    assert result.content_changed
    assert session.get(RawDocument, doc_id).body_text == "edited"
    assert session.get(Document, doc_id).processed_at is None


def test_threading_fields_are_kept(session, clock):
    store = _store(session, clock)
    doc_id = store.save(
        _doc(external_id="101", parent_external_id="100", thread_external_id="100")
    ).document_id
    doc = session.get(Document, doc_id)
    assert (doc.parent_external_id, doc.thread_external_id) == ("100", "100")


def test_deletion_removes_text_but_keeps_the_fact(session, clock):
    store = _store(session, clock)
    doc_id = store.save(
        _doc(comments=[CommentIn(external_id="c1", body_text="reply text")])
    ).document_id
    cls = ClassificationRun(
        classification_id="cls_test",
        document_id=doc_id,
        content_hash=session.get(Document, doc_id).content_hash,
        run_id=session.get(Document, doc_id).collect_run_id,
        model="m",
        prompt_version="p",
        schema_version="s",
        status=ClassificationStatus.ACCEPTED,
        requested_at=T0,
        completed_at=T0,
    )
    session.add(cls)
    session.flush()
    session.add(
        Claim(
            claim_id="clm_test",
            document_id=doc_id,
            classification_id="cls_test",
            subject_text="NVIDIA",
            predicate=EdgeType.RELATED_TO,
            object_text="HBM",
            polarity=Polarity.NEUTRAL,
            stance=Stance.NEUTRAL,
            evidence_status=EvidenceStatus.COMMUNITY_OPINION,
            excerpt="quoted words",
            created_at=T0,
            available_at=T0,
        )
    )
    session.flush()

    deleted_at = T0 + timedelta(hours=2)
    assert store.mark_deleted("hackernews", "100", deleted_at)
    session.flush()
    doc = session.get(Document, doc_id)
    assert doc.deleted_observed_at == deleted_at
    assert doc.title == ""
    assert session.get(RawDocument, doc_id) is None
    assert session.scalar(sa.select(sa.func.count()).select_from(DocumentComment)) == 0
    assert session.get(Claim, "clm_test").excerpt is None

    # 지워진 글은 다시 받아도 되살리지 않는다
    again = store.save(_doc(observed=T0 + timedelta(hours=3)))
    assert again.ignored_deleted
    assert session.get(RawDocument, doc_id) is None
    assert store.mark_deleted("hackernews", "never-seen", deleted_at) is False


def test_author_deletion_removes_all_their_documents(session, clock):
    store = _store(session, clock)
    store.save(_doc(external_id="1"))
    store.save(_doc(external_id="2"))
    store.save(_doc(external_id="3", author_hash="b" * 64))
    assert store.mark_author_deleted("hackernews", "a" * 64, T0 + timedelta(hours=1)) == 2
    session.flush()
    remaining = session.scalars(
        sa.select(Document.external_id).where(Document.deleted_observed_at.is_(None))
    ).all()
    assert remaining == ["3"]


def test_metadata_only_documents_store_no_text(session, clock):
    store = _store(session, clock)
    doc_id = store.save(_doc(content_access_status="metadata_only")).document_id
    assert session.get(Document, doc_id).title == ""
    assert session.get(RawDocument, doc_id) is None


def test_run_and_health_rows(session, clock):
    seed_defaults(session, clock)
    run = start_run(session, clock, RunKind.COLLECT, params={"source": "hackernews"})
    assert run.status == RunStatus.RUNNING
    finish_run(run, clock.now(), RunStatus.SUCCEEDED)
    row = record_health(
        session,
        clock,
        "hackernews",
        T0,
        T0,
        SourceHealthStatus.OK,
        requests=3,
        successes=3,
    )
    session.flush()
    assert row.window_end > row.window_start
    assert session.scalar(sa.select(sa.func.count()).select_from(SourceHealth)) == 1

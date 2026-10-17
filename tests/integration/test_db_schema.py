from datetime import UTC, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from narrative_radar.core.ids import new_id
from narrative_radar.db.models import (
    APPEND_ONLY_TABLES,
    Base,
    Document,
    Edge,
    GraphEvent,
    InterestProfile,
    Node,
    NodeAlias,
    PipelineRun,
    ProfileNode,
    SourceAdapter,
)
from narrative_radar.db.seed import seed_defaults
from narrative_radar.db.session import make_engine
from narrative_radar.schemas.enums import (
    ContentAccessStatus,
    EdgeStatus,
    EdgeType,
    EventCause,
    EventType,
    IngestMode,
    NodeStatus,
    NodeType,
    RunKind,
    RunMode,
    RunStatus,
    SourceAccessStatus,
    SourceKind,
)

ALL_SOURCE_IDS = {
    "bluesky_jetstream",
    "hackernews",
    "gdelt",
    "web",
    "dcinside_stockus",
    "naver_world_nvda",
}

KST = timezone(timedelta(hours=9))


def _run(session, clock) -> PipelineRun:
    now = clock.now()
    run = PipelineRun(
        run_id=new_id("run", now),
        kind=RunKind.COLLECT,
        mode=RunMode.LIVE,
        status=RunStatus.SUCCEEDED,
        started_at=now,
        code_version="test",
    )
    session.add(run)
    session.flush()
    return run


def _document(session, clock, run, external_id="123", published_at=None) -> Document:
    now = clock.now()
    doc = Document(
        document_id=new_id("doc", now),
        source_adapter_id="dcinside_stockus",
        source="dcinside",
        source_type=SourceKind.COMMUNITY,
        external_id=external_id,
        source_url=f"https://example.com/{external_id}",
        title="example",
        published_at=published_at or now,
        observed_at=now,
        content_hash="0" * 64,
        content_access_status=ContentAccessStatus.UNVERIFIED,
        ingest_mode=IngestMode.LIVE,
        collect_run_id=run.run_id,
    )
    session.add(doc)
    session.flush()
    return doc


def test_migration_matches_models(db_url):
    engine = make_engine(db_url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    engine.dispose()
    assert diff == []


def test_append_only_tables_reject_update_and_delete(session, clock):
    seed_defaults(session, clock)
    session.commit()
    event = session.scalars(sa.select(GraphEvent)).one()
    for stmt in (
        sa.update(GraphEvent).values(cause=EventCause.REPROCESS),
        sa.delete(GraphEvent),
    ):
        with pytest.raises(sa.exc.DatabaseError, match="append-only"):
            session.execute(stmt)
        session.rollback()
    assert session.get(GraphEvent, event.event_id).cause == EventCause.USER_ACTION


def test_every_append_only_table_has_triggers(db_url):
    engine = make_engine(db_url)
    with engine.connect() as conn:
        names = set(
            conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='trigger'")).scalars()
        )
    engine.dispose()
    for table in APPEND_ONLY_TABLES:
        assert f"trg_{table}_no_update" in names
        assert f"trg_{table}_no_delete" in names


def test_datetimes_are_stored_as_utc_and_naive_values_are_rejected(session, clock):
    seed_defaults(session, clock)
    run = _run(session, clock)
    doc = _document(session, clock, run, published_at=datetime(2026, 10, 13, 10, 0, tzinfo=KST))
    session.commit()
    session.expire_all()
    loaded = session.get(Document, doc.document_id)
    assert loaded.published_at == datetime(2026, 10, 13, 1, 0, tzinfo=UTC)
    assert loaded.published_at.tzinfo is UTC

    with pytest.raises(sa.exc.StatementError, match="naive datetime"):
        _document(session, clock, run, external_id="999", published_at=datetime(2026, 10, 13))  # noqa: DTZ001
    session.rollback()


def test_same_source_document_cannot_be_stored_twice(session, clock):
    seed_defaults(session, clock)
    run = _run(session, clock)
    _document(session, clock, run, external_id="dup")
    with pytest.raises(sa.exc.IntegrityError):
        _document(session, clock, run, external_id="dup")


def test_edges_reject_self_loops_and_duplicate_relations(session, clock):
    seed_defaults(session, clock)
    run = _run(session, clock)
    root = session.scalars(sa.select(Node)).one()
    now = clock.now()

    def edge(src, dst, rel=EdgeType.RELATED_TO):
        session.add(
            Edge(
                edge_id=new_id("edg", now),
                source_node_id=src,
                target_node_id=dst,
                relation_type=rel,
                status=EdgeStatus.CANDIDATE,
                created_at=now,
                available_at=now,
                created_run_id=run.run_id,
            )
        )
        session.flush()

    with pytest.raises(sa.exc.IntegrityError):
        edge(root.node_id, root.node_id)
    session.rollback()

    seed_defaults(session, clock)
    run = _run(session, clock)
    root = session.scalars(sa.select(Node)).one()
    other = Node(
        node_id=new_id("nod", now),
        canonical_key="TOPIC:HBM",
        node_type=NodeType.TOPIC,
        label="HBM",
        status=NodeStatus.CANDIDATE,
        created_at=now,
        available_at=now,
        created_run_id=run.run_id,
    )
    session.add(other)
    session.flush()
    edge(root.node_id, other.node_id)
    with pytest.raises(sa.exc.IntegrityError):
        edge(root.node_id, other.node_id)


def test_graph_event_needs_a_target(session, clock):
    seed_defaults(session, clock)
    run = _run(session, clock)
    now = clock.now()
    session.add(
        GraphEvent(
            event_id=new_id("evt", now),
            event_type=EventType.NODE_CREATED,
            cause=EventCause.OBSERVED_NEW,
            recorded_at=now,
            available_at=now,
            run_id=run.run_id,
        )
    )
    with pytest.raises(sa.exc.IntegrityError):
        session.flush()


def test_invalid_enum_value_is_rejected_before_write(session, clock):
    seed_defaults(session, clock)
    with pytest.raises(sa.exc.StatementError):
        session.execute(
            sa.update(SourceAdapter).values(access_status="definitely_live")  # type: ignore[arg-type]
        )


def test_seed_is_idempotent_and_starts_with_collection_off(session, clock):
    seed_defaults(session, clock)
    seed_defaults(session, clock)
    session.commit()

    sources = session.scalars(sa.select(SourceAdapter)).all()
    assert {s.source_adapter_id for s in sources} == ALL_SOURCE_IDS
    assert all(s.access_status == SourceAccessStatus.NOT_AUTHORIZED for s in sources)
    assert all(not s.live_enabled for s in sources)

    assert session.scalar(sa.select(sa.func.count()).select_from(InterestProfile)) == 1
    root = session.scalars(sa.select(Node)).one()
    assert (root.canonical_key, root.label) == ("US:NVDA", "NVIDIA")
    aliases = set(session.scalars(sa.select(NodeAlias.alias_normalized)))
    assert {"nvidia", "nvda", "엔비디아", "nvidia corporation"} <= aliases
    decision = session.scalars(sa.select(ProfileNode)).one()
    assert decision.depth == 0
    event = session.scalars(sa.select(GraphEvent)).one()
    assert (event.event_type, event.cause) == (EventType.NODE_CREATED, EventCause.USER_ACTION)

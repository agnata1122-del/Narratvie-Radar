"""도메인 팩: 분야 공통 유형·키 규칙, 예전 값 호환, 마이그레이션 (DECISIONS D22)."""

import json

import pytest
import sqlalchemy as sa
from alembic import command

from narrative_radar.classifiers.session import ingest_records
from narrative_radar.db.migrate import alembic_config
from narrative_radar.db.models import ClassificationRun, InterestProfile, Node
from narrative_radar.db.seed import seed_defaults
from narrative_radar.db.session import make_engine, make_session_factory
from narrative_radar.domains import get_pack, pack_for_profiles, valid_key
from narrative_radar.ingest.runs import start_run
from narrative_radar.ingest.store import DocumentStore
from narrative_radar.schemas.classification import ClassificationOutput
from narrative_radar.schemas.document import DocumentIn
from narrative_radar.schemas.enums import NodeType, RunKind


@pytest.mark.parametrize(
    ("node_type", "key", "ok"),
    [
        (NodeType.ORGANIZATION, "ORG:krafton", True),
        (NodeType.PERSON, "PERSON:jensen-huang", True),
        (NodeType.PRODUCT, "PRODUCT:battlegrounds", True),
        (NodeType.PLACE, "PLACE:taiwan", True),
        (NodeType.ORGANIZATION, "US:NVDA", True),  # 금융 팩의 티커 키
        (NodeType.ORGANIZATION, "COMPANY:openai", True),  # 예전 키
        (NodeType.TOPIC, "INDUSTRY:semiconductors", True),  # 금융 팩의 산업 키
        (NodeType.PERSON, "US:NVDA", False),  # 티커는 조직에만
        (NodeType.TOPIC, "FOO:bar", False),
        (NodeType.ORGANIZATION, "ORG:Krafton", False),  # 슬러그는 소문자
    ],
)
def test_keys_follow_core_rules_plus_registered_packs(node_type, key, ok):
    assert valid_key(node_type, key) is ok


def test_pack_choice_follows_profiles():
    assert pack_for_profiles([]).id == "general"
    assert pack_for_profiles(["finance", "finance"]).id == "finance"
    with pytest.raises(ValueError, match="--domain"):
        pack_for_profiles(["finance", "general"])
    with pytest.raises(ValueError, match="unknown domain pack"):
        get_pack("nope")
    assert "shadow_trading" in get_pack("finance").lenses
    assert get_pack("general").lenses == ()


def test_legacy_v1_values_are_read_as_generic_values():
    out = ClassificationOutput.model_validate(
        {
            "relevance": 0.9,
            "is_noise": False,
            "entities": [
                {"name": "NVIDIA", "type": "company", "canonical_key": "US:NVDA"},
                {"name": "semis", "type": "industry", "canonical_key": "INDUSTRY:semiconductors"},
            ],
            "stance": "bullish",
            "claims": [
                {
                    "subject": "semis",
                    "predicate": "AFFECTS",
                    "object": "NVIDIA",
                    "polarity": "growth_driver",
                    "stance": "bearish",
                    "evidence_status": "speculation",
                    "excerpt": "example",
                }
            ],
            "needs_review": False,
        }
    )
    dumped = out.model_dump(mode="json")
    assert [e["type"] for e in dumped["entities"]] == ["organization", "topic"]
    assert dumped["stance"] == "positive"
    assert (dumped["claims"][0]["polarity"], dumped["claims"][0]["stance"]) == (
        "enabler",
        "negative",
    )


def test_ingest_stores_generic_values_even_from_legacy_output(session, clock):
    seed_defaults(session, clock)
    store = DocumentStore(session, start_run(session, clock, RunKind.COLLECT).run_id, "test")
    doc_id = store.save(
        DocumentIn(
            source_adapter_id="hackernews",
            external_id="1",
            source_url="https://news.ycombinator.com/item?id=1",
            title="",
            body_text="example text about NVIDIA",
            published_at=clock.now(),
            observed_at=clock.now(),
            content_access_status="permitted",
            ingest_mode="live",
        )
    ).document_id
    from narrative_radar.db.models import Document

    doc = session.get(Document, doc_id)
    line = json.dumps(
        {
            "document_id": doc.document_id,
            "content_hash": doc.content_hash,
            "output": {
                "relevance": 0.9,
                "is_noise": False,
                "entities": [{"name": "NVIDIA", "type": "company", "canonical_key": "US:NVDA"}],
                "stance": "bullish",
                "claims": [],
                "needs_review": False,
            },
        }
    )
    run_id = start_run(session, clock, RunKind.CLASSIFY).run_id
    report = ingest_records(session, clock, [line], "test-model", run_id)
    assert report.accepted == 1
    stored = session.scalars(sa.select(ClassificationRun)).one().output
    assert stored["entities"][0]["type"] == "organization" and stored["stance"] == "positive"


def test_migration_converts_legacy_rows_and_sets_profile_domain(db_url, clock):
    """head → 예전 값으로 되돌린 상태(0007) → 다시 head: 예전 값이 공통 값으로 바뀐다."""
    engine = make_engine(db_url)
    with make_session_factory(engine).begin() as session:
        seed_defaults(session, clock)
    cfg = alembic_config(db_url)
    command.downgrade(cfg, "0007")
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT node_type FROM nodes")).scalar_one() == "company"
        cols = {r[1] for r in conn.execute(sa.text("PRAGMA table_info(interest_profiles)"))}
        assert "domain" not in cols
    command.upgrade(cfg, "head")
    with make_session_factory(engine)() as session:
        node = session.scalars(sa.select(Node)).one()
        assert node.node_type == NodeType.ORGANIZATION
        assert session.scalars(sa.select(InterestProfile.domain)).one() == "finance"
    engine.dispose()

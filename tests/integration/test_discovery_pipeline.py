"""발견에서 트리·위키·재생까지: 소유자 우선순위 3→7을 한 흐름으로 확인한다 (DECISIONS D23·D25).

GDELT 응답과 분류 결과는 형식 확인용으로 직접 작성한 예시다. 예시용 도메인만 쓴다
(DECISIONS D0 예외).
"""

import json
from datetime import timedelta

import httpx
import sqlalchemy as sa
from graphkit import HBM, NV, SKH, affects
from test_discovery import FakeGdelt, article

from narrative_radar.classifiers.session import export_batch
from narrative_radar.collectors.gate import set_status
from narrative_radar.collectors.http import PoliteClient
from narrative_radar.collectors.rate_limit import MinIntervalLimiter
from narrative_radar.core.config import Settings
from narrative_radar.db.models import Document, Node, WikiRevision
from narrative_radar.discovery.branch import create_branch
from narrative_radar.discovery.expansion import expand_profile
from narrative_radar.discovery.providers import GdeltProvider
from narrative_radar.discovery.run import plan_queries, run_discovery
from narrative_radar.domains import get_pack
from narrative_radar.ingest.runner import RunContext
from narrative_radar.ingest.runs import start_run
from narrative_radar.schemas.enums import EdgeStatus, RunKind, SourceAccessStatus
from narrative_radar.temporal.state import graph_state
from narrative_radar.wiki.build import refresh_wiki

SALT = "s" * 32
PACKAGING = ("advanced packaging", "topic", "TOPIC:advanced-packaging")
TITLE_A = "Example headline: advanced packaging lines expand HBM output this quarter"
TITLE_B = "Second sample report says chip packaging capacity is what limits HBM growth"


def test_discovered_headlines_grow_the_branch_tree_and_its_wiki(
    g, clock, session_factory, tmp_path
):
    g.confirm(HBM, NV)
    g.confirm(SKH, HBM, words=("third wording sample", "fourth wording different entirely"))
    g.build()
    hbm_branch = create_branch(g.session, clock, g.profile, g.node("TECH:hbm").node_id).profile
    g.session.commit()
    with session_factory.begin() as s:
        set_status(s, "gdelt", SourceAccessStatus.LIVE, "test", clock, live_enabled=True)
    before = clock.now()
    clock.advance(timedelta(hours=1))

    # 3. 발견: HBM 가지의 검색이 두 사이트의 헤드라인을 찾는다
    seen = clock.now() - timedelta(minutes=20)
    fake = FakeGdelt(
        {
            "HBM": lambda: httpx.Response(
                200,
                json={
                    "articles": [
                        article("https://example.com/p", TITLE_A, seen),
                        article("https://news.example.org/q", TITLE_B, seen, "news.example.org"),
                    ]
                },
            )
        }
    )
    ctx = RunContext(
        Settings(live_collection_enabled=True, author_hash_salt=SALT),
        session_factory,
        clock,
        "gdelt",
    )
    client = PoliteClient(
        "NarrativeRadar/test",
        limiter=MinIntervalLimiter(0),
        guard=ctx.guard(),
        transport=httpx.MockTransport(fake),
    )
    provider = GdeltProvider(client)
    with session_factory() as s:
        plan = plan_queries(s, provider, clock.now(), 20)
    hbm_query = next(q for q in plan.queries if q.query == "HBM")
    assert hbm_query.profile_id == hbm_branch.profile_id  # HBM은 자기 가지의 몫으로 검색된다
    with ctx.run(RunKind.COLLECT, {}) as run_id:
        assert run_discovery(ctx, provider, run_id, plan).documents == 2

    # 5. 분류용 내보내기: 헤드라인 표시와 기존 노드 단서가 붙는다
    g.session.expire_all()
    export_batch(g.session, clock, 20, tmp_path, get_pack("finance"))
    lines = {
        json.loads(line)["text"]: json.loads(line)
        for line in (tmp_path / "batch.jsonl").read_text().splitlines()
    }
    a = lines[TITLE_A]
    assert a["headline_only"] is True
    assert [k["canonical_key"] for k in a["known_nodes"]] == ["TECH:hbm"]

    # 세션 분류 결과 (형식 예시). 하나는 SK하이닉스를 기존 키 대신 새 키로 잘못 제안했다
    docs = {
        d.title: d for d in g.session.scalars(sa.select(Document).where(Document.source == "web"))
    }
    claim = affects(PACKAGING[0], "HBM", evidence_status="reported_fact")
    g.classify(docs[TITLE_A], [HBM, PACKAGING], [claim])
    g.classify(
        docs[TITLE_B],
        [HBM, PACKAGING, ("SK hynix", "organization", "ORG:sk-hynix")],
        [claim],
    )
    g.build()
    expand_profile(g.session, clock, start_run(g.session, clock, RunKind.BUILD).run_id, hbm_branch)

    # 기존 노드에 이어 붙고 같은 대상을 새로 만들지 않는다
    keys = list(g.session.scalars(sa.select(Node.canonical_key)))
    assert keys.count("TECH:hbm") == 1 and "ORG:sk-hynix" not in keys
    assert g.edge("TOPIC:advanced-packaging", "TECH:hbm").status == EdgeStatus.CONFIRMED

    # 4·D23. 새 노드는 HBM 가지에서 1단계, 공통 그래프에 하나만 있다
    now_state = graph_state(g.session, hbm_branch, clock.now())
    depth = {node.canonical_key: node.depth for node in now_state.nodes}
    assert depth["TOPIC:advanced-packaging"] == 1

    # 6. 위키: 새 노드의 문서가 생긴다
    wiki_run = start_run(g.session, clock, RunKind.WIKI).run_id
    refresh_wiki(g.session, clock, wiki_run, [g.profile, hbm_branch])
    packaging = g.node("TOPIC:advanced-packaging")
    assert g.session.scalar(
        sa.select(WikiRevision.revision_id).where(WikiRevision.node_id == packaging.node_id)
    )

    # 7. 재생: 발견 전 시점에는 없었다
    then = {node.canonical_key for node in graph_state(g.session, hbm_branch, before).nodes}
    assert "TOPIC:advanced-packaging" not in then and "TECH:hbm" in then

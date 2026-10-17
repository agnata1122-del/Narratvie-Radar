"""소유자가 관심사 트리에 노드를 직접 넣는 규칙 테스트."""

from narrative_radar.discovery.curation import admit_node
from narrative_radar.ingest.runner import profile_keys, profile_terms
from narrative_radar.ingest.runs import start_run
from narrative_radar.schemas.enums import NodeStatus, NodeType, RunKind


def _admit(g, clock, key="KR:000660", aliases=("SK하이닉스", "하이닉스")):
    run = start_run(g.session, clock, RunKind.SETUP).run_id
    return admit_node(
        g.session,
        clock,
        run,
        g.profile,
        key,
        "SK hynix",
        NodeType.ORGANIZATION,
        aliases,
        1,
        "MVP case",
    )


def test_admitted_node_aliases_become_search_terms(g, clock):
    report = _admit(g, clock)
    assert report.node_created and report.admitted
    assert g.node("KR:000660").status == NodeStatus.ACTIVE
    terms = profile_terms(g.session, clock.now())
    assert {"SK hynix", "SK하이닉스", "하이닉스"} <= set(terms)
    assert "SK hynix" in profile_terms(g.session, clock.now(), ascii_only=True)
    assert "KR:000660" in profile_keys(g.session, clock.now())  # 시세 대상


def test_admitting_again_only_adds_new_aliases(g, clock):
    _admit(g, clock)
    again = _admit(g, clock, aliases=("하이닉스", "하닉"))
    assert not again.node_created and not again.admitted
    assert again.aliases_added == ["하닉"]


def test_existing_candidate_node_is_admitted(g, clock):
    g.classify(
        g.doc("HBM supply example text with enough words here"), [("HBM", "technology", "TECH:hbm")]
    )
    g.build()
    report = _admit(g, clock, key="TECH:hbm", aliases=("고대역폭 메모리",))
    assert not report.node_created and report.admitted
    assert "고대역폭 메모리" in profile_terms(g.session, clock.now())

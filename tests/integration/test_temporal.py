"""시점별 상태, 내러티브 상태, 달라진 점, 위키 리비전 테스트."""

import dataclasses
from datetime import timedelta

import sqlalchemy as sa
from graphkit import FILLER, HBM, NV, POWER, SKH, affects

from narrative_radar.db.models import Document, Viewer, ViewerOverlay, WikiRevision
from narrative_radar.ingest.health import record_health
from narrative_radar.ingest.runs import start_run
from narrative_radar.schemas.enums import (
    NarrativeState,
    RunKind,
    SourceHealthStatus,
    TargetType,
    ViewerDecision,
)
from narrative_radar.temporal.changes import what_changed
from narrative_radar.temporal.narratives import narrative_state_at
from narrative_radar.temporal.state import graph_state
from narrative_radar.wiki.build import latest_revision, refresh_wiki


def _state(g, t, **kw):
    return graph_state(g.session, g.profile, t, **kw)


def _ids(state):
    return {n.canonical_key for n in state.nodes}


def test_state_reflects_only_what_was_known_at_each_time(g, clock):
    t0 = clock.now()
    g.post(f"alpha HBM NVIDIA {FILLER}", [NV, HBM], [affects("HBM", "NVIDIA")], author="a")
    g.build()
    t1 = clock.now()
    clock.advance(timedelta(days=1))
    g.post(
        f"beta other words HBM NVIDIA {FILLER}", [NV, HBM], [affects("HBM", "NVIDIA")], author="b"
    )
    g.build()
    t2 = clock.now()

    s1 = _state(g, t1)
    hbm1 = next(n for n in s1.nodes if n.canonical_key == "TECH:hbm")
    assert hbm1.membership == "pending_review"
    assert {e.status for e in s1.edges if e.relation == "AFFECTS"} == {"candidate"}

    s2 = _state(g, t2)
    hbm2 = next(n for n in s2.nodes if n.canonical_key == "TECH:hbm")
    assert hbm2.membership == "admitted"
    assert {e.status for e in s2.edges if e.relation == "AFFECTS"} == {"confirmed"}

    # 루트가 생기기 전에는 아무것도 없다
    assert _state(g, t0 - timedelta(seconds=1)).nodes == []


def test_later_information_never_changes_past_state(g, clock):
    g.confirm(HBM, NV)
    g.build()
    checkpoints = []
    for i in range(3):
        checkpoints.append(clock.now())
        clock.advance(timedelta(hours=6))
        g.post(
            f"round {i} {'x' * i} SK hynix HBM {FILLER}",
            [SKH, HBM],
            [affects("SK hynix", "HBM")],
            author="abc"[i],
        )
        g.build()
    before = [dataclasses.asdict(_state(g, t)) for t in checkpoints]

    # 나중에 백필로 과거 글이 들어오고, 관계가 더 확정되어도
    clock.advance(timedelta(days=1))
    g.post(
        f"late old post about power {FILLER}",
        [NV, POWER],
        [affects("data center power", "NVIDIA")],
        mode="backfill",
        published=checkpoints[0] - timedelta(hours=1),
    )
    g.confirm(POWER, NV, words=("gamma words here", "delta totally different phrasing"))
    g.build()

    after = [dataclasses.asdict(_state(g, t)) for t in checkpoints]
    assert before == after


def test_activity_share_and_dormancy(g, clock):
    g.confirm(HBM, NV)  # 글 2개
    g.post(f"one more mention NVIDIA HBM {FILLER}", [NV, HBM], author="c")
    g.post(f"unrelated noise {FILLER}", [NV], is_noise=True)
    g.build()
    now = clock.now()
    s = _state(g, now)
    root = next(n for n in s.nodes if n.membership == "root")
    assert root.mentions_7d == 3 and root.share_7d == 0.75
    clock.advance(timedelta(days=4))
    s_later = _state(g, clock.now())
    hbm = next(n for n in s_later.nodes if n.canonical_key == "TECH:hbm")
    assert hbm.dormant and hbm.status == "dormant"
    root_later = next(n for n in s_later.nodes if n.membership == "root")
    assert root_later.activity < root.activity and not root_later.dormant


def test_viewer_overlay_hides_nodes_only_for_that_viewer(g, clock):
    g.confirm(HBM, NV)
    g.build()
    now = clock.now()
    g.session.add(Viewer(viewer_id="vwr_1", created_at=now, last_seen_at=now))
    g.session.add(
        ViewerOverlay(
            viewer_id="vwr_1",
            profile_id=g.profile.profile_id,
            target_type=TargetType.NODE,
            target_id=g.node("TECH:hbm").node_id,
            decision=ViewerDecision.REJECTED,
            created_at=now,
        )
    )
    g.session.flush()
    assert "TECH:hbm" not in _ids(_state(g, now, viewer_id="vwr_1"))
    assert "TECH:hbm" in _ids(_state(g, now))


def _narrative_post(g, role, author, words, key=None):
    extra = {"narrative_role": role}
    if key:
        extra["narrative_key"] = key
    else:
        extra["narrative_proposition"] = "HBM supply limits NVIDIA"
    g.post(
        f"{words} HBM NVIDIA {FILLER}",
        [NV, HBM],
        [affects("HBM", "NVIDIA", **extra)],
        author=author,
    )


def test_narrative_states_over_time(g, clock):
    _narrative_post(g, "supports", "a", "first")
    g.build()
    key = g.session.scalar(
        sa.select(sa.text("canonical_key"))
        .select_from(sa.text("nodes"))
        .where(sa.text("node_type = 'narrative'"))
    )
    nar_id = g.session.scalar(sa.text("select narrative_id from narratives"))
    assert narrative_state_at(g.session, nar_id, clock.now()).state == NarrativeState.EMERGING

    clock.advance(timedelta(days=8))
    for i, author in enumerate("bcde"):
        _narrative_post(g, "supports", author, f"wave {i} {'y' * i}", key)
    g.build()
    assert narrative_state_at(g.session, nar_id, clock.now()).state == NarrativeState.SPREADING

    clock.advance(timedelta(days=8))
    for i, author in enumerate("fghi"):
        _narrative_post(g, "contradicts", author, f"pushback {i} {'z' * i}", key)
    g.build()
    assert narrative_state_at(g.session, nar_id, clock.now()).state == NarrativeState.REVERSED

    clock.advance(timedelta(days=8))
    assert narrative_state_at(g.session, nar_id, clock.now()).state == NarrativeState.FADING


def test_what_changed_lists_new_things_with_cause_and_evidence(g, clock):
    since = clock.now()
    clock.advance(timedelta(hours=1))
    g.confirm(HBM, NV)
    g.build()
    report = what_changed(g.session, g.profile, since, clock.now())
    kinds = {(i.kind, i.label) for i in report.items}
    assert ("new_node", "HBM") in kinds
    assert ("new_relation", "HBM → NVIDIA") in kinds
    item = next(i for i in report.items if i.kind == "new_relation")
    assert item.cause == "observed_new" and item.independent == 2 and item.spread_documents == 2
    assert len(item.evidence) == 2 and all(e.url.startswith("https://") for e in item.evidence)


def test_what_changed_marks_backfill_cause(g, clock):
    since = clock.now()
    clock.advance(timedelta(hours=1))
    for author, words in (("a", "old one"), ("b", "old two different")):
        g.post(
            f"{words} HBM NVIDIA {FILLER}",
            [NV, HBM],
            [affects("HBM", "NVIDIA")],
            author=author,
            mode="backfill",
            published=since - timedelta(days=2),
        )
    g.build()
    report = what_changed(g.session, g.profile, since, clock.now())
    assert {i.cause for i in report.items if i.kind in ("new_node", "new_relation")} == {"backfill"}


def test_observation_gap_suppresses_attention_drop(g, clock):
    for i in range(6):
        g.post(f"busy {i} {'w' * i} NVIDIA HBM {FILLER}", [NV, HBM], author="abcdef"[i])
    g.confirm(HBM, NV)
    g.build()
    since = clock.now()
    clock.advance(timedelta(days=6))
    for i in range(20):
        g.post(f"other topic {i} {'q' * i} NVIDIA {FILLER}", [NV], author="abcdefghijklmnopqrst"[i])
    g.build()
    until = clock.now()
    drops = [
        i
        for i in what_changed(g.session, g.profile, since, until).items
        if i.kind == "attention_down"
    ]
    assert [d.label for d in drops] == ["HBM"]

    record_health(
        g.session,
        clock,
        "hackernews",
        since + timedelta(days=1),
        since + timedelta(days=2),
        SourceHealthStatus.DOWN,
        note="collector stopped",
    )
    g.session.flush()
    report = what_changed(g.session, g.profile, since, until)
    assert not [i for i in report.items if i.kind == "attention_down"]
    assert [gap.status for gap in report.gaps] == ["down"]


def test_deleted_documents_are_not_shown_as_evidence(g, clock):
    since = clock.now()
    clock.advance(timedelta(hours=1))
    g.confirm(HBM, NV)
    g.build()
    doc = g.session.scalars(sa.select(Document).order_by(Document.published_at)).first()
    g.store.mark_deleted(doc.source_adapter_id, doc.external_id, clock.now())
    g.session.flush()
    item = next(
        i
        for i in what_changed(g.session, g.profile, since, clock.now()).items
        if i.kind == "new_relation"
    )
    assert doc.document_id not in {e.document_id for e in item.evidence}


def test_wiki_revisions_are_versioned_and_time_travel(g, clock):
    run = start_run(g.session, clock, RunKind.WIKI).run_id
    g.confirm(HBM, NV, words=("first wording here", "second wording entirely different"))
    g.build()
    created, _ = refresh_wiki(g.session, clock, run, g.profile)
    assert created == 2  # NVIDIA, HBM
    t1 = clock.now()
    again, unchanged = refresh_wiki(g.session, clock, run, g.profile)
    assert (again, unchanged) == (0, 2)

    clock.advance(timedelta(hours=2))
    g.confirm(SKH, HBM)
    g.build()
    refresh_wiki(g.session, clock, run, g.profile)
    hbm = g.node("TECH:hbm").node_id
    latest = latest_revision(g.session, hbm)
    past = latest_revision(g.session, hbm, as_of=t1)
    assert latest.version == 2 and past.version == 1
    related_now = next(s for s in latest.sections if s["key"] == "related")["markdown"]
    related_then = next(s for s in past.sections if s["key"] == "related")["markdown"]
    assert "SK hynix" in related_now and "SK hynix" not in related_then
    assert g.session.scalar(sa.select(sa.func.count()).select_from(WikiRevision)) >= 4
    overview = next(s for s in latest.sections if s["key"] == "overview")["markdown"]
    assert "사실 확인을 거치지 않았다" in overview


def test_narrative_node_is_active_and_its_links_stay_confirmed_in_state(g, clock):
    # 내러티브를 지지한 글은 내러티브 노드의 언급으로 센다. 같은 반영에서 생기고 확정된 연결은
    # 시점별 상태에서도 확정으로 남아야 한다 (이벤트 순서 = ID 순서).
    for author, w in (("a", "alpha words"), ("b", "beta other words entirely")):
        g.post(
            f"{w} HBM NVIDIA {FILLER}",
            [NV, HBM],
            [
                affects(
                    "HBM",
                    "NVIDIA",
                    narrative_proposition="HBM supply limits NVIDIA",
                    narrative_role="supports",
                )
            ],
            author=author,
        )
    g.build()
    state = _state(g, clock.now())
    narrative = next(n for n in state.nodes if n.node_type == "narrative")
    assert narrative.mentions_7d == 2 and not narrative.dormant
    links = [e for e in state.edges if narrative.node_id in (e.source, e.target)]
    assert len(links) == 2 and {e.status for e in links} == {"confirmed"}

"""과거 시점 재생 (R2, DECISIONS D41).

글과 분류 결과는 규칙 확인용으로 직접 만든 최소 예시다 (DECISIONS D0 예외).
"""

from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa
from graphkit import FILLER, HBM, NV, POWER, SKH, GraphKit, affects

from narrative_radar.core.clock import FixedClock
from narrative_radar.db.migrate import upgrade_to_head
from narrative_radar.db.models import Base, Node
from narrative_radar.db.session import make_engine, make_session_factory
from narrative_radar.temporal.replay import end_of_day, replay
from narrative_radar.temporal.state import graph_state

DAY0 = date(2026, 3, 1)
D1, D2, D3 = (DAY0 + timedelta(days=i) for i in (1, 2, 3))

# (게시일, 글 앞부분, 개체, 관계, 작성자): 날마다 서로 다른 작성자 두 명이 같은 관계를 말한다
POSTS = [
    (D1, "alpha words", NV, HBM, "a"),
    (D1, "beta other words entirely", NV, HBM, "b"),
    (D2, "gamma lines about memory", HBM, SKH, "c"),
    (D2, "delta second memory note", HBM, SKH, "d"),
    (D3, "epsilon power grid post", POWER, NV, "e"),
    (D3, "zeta another grid comment", POWER, NV, "f"),
]


def _world(tmp_path, name, last_day=D3, classified_on=None):
    """새 DB에 같은 글을 올린다. classified_on: 분류를 그날 한 것으로 둔다(기본은 시작 전)."""
    url = f"sqlite:///{tmp_path / name}.db"
    upgrade_to_head(url)
    session = make_session_factory(make_engine(url))()
    clock = FixedClock(datetime.combine(DAY0, datetime.min.time(), tzinfo=UTC))
    g = GraphKit(session, clock)
    if classified_on:
        clock.advance(end_of_day(classified_on) - clock.now())
    for day, words, a, b, author in POSTS:
        if day > last_day:
            continue
        published = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)
        g.post(
            f"{words} {a[0]} {b[0]} {FILLER}",
            [a, b],
            [affects(a[0], b[0])],
            author=author,
            published=published,
        )
    session.commit()
    return g


def _summary(g, day):
    """시점 상태를 ID 없이 키로 적는다 (ID는 실행마다 다르다). 처음 본 시각도 뺀다."""
    state = graph_state(g.session, g.profile, end_of_day(day))
    keys = dict(g.session.execute(sa.select(Node.node_id, Node.canonical_key)).all())
    nodes = sorted(
        (n.canonical_key, n.status, n.membership, n.depth, round(n.activity, 9), n.mentions_7d)
        for n in state.nodes
    )
    edges = sorted(
        (keys[e.source], e.relation, keys[e.target], e.status, e.independent_evidence)
        for e in state.edges
    )
    return nodes, edges


def test_replay_to_t_matches_later_replay_and_fresh_build(tmp_path):
    partial = _world(tmp_path, "partial")  # 모든 글이 있지만 D2까지만 재생
    replay(partial.session, D1, D2, assume_timely=True)
    full = _world(tmp_path, "full")  # 같은 글, D3까지 재생
    replay(full.session, D1, D3, assume_timely=True)
    fresh = _world(tmp_path, "fresh", last_day=D2)  # D2까지의 글만으로 새로 만듦
    replay(fresh.session, D1, D2, assume_timely=True)

    for day in (D1, D2):
        assert _summary(partial, day) == _summary(full, day) == _summary(fresh, day)
    nodes, _ = _summary(full, D2)
    assert ("TECH:hbm", "active", "admitted", 1) in {n[:4] for n in nodes}
    assert "TOPIC:data-center-power" not in {n[0] for n in nodes}
    assert "TOPIC:data-center-power" in {n[0] for n in _summary(full, D3)[0]}


def test_no_record_is_available_after_the_replayed_day(tmp_path):
    g = _world(tmp_path, "w")
    replay(g.session, D1, D2, assume_timely=True)
    t = end_of_day(D2)
    late = {
        table.name: g.session.scalar(
            sa.select(sa.func.count()).select_from(table).where(table.c.available_at > t)
        )
        for table in Base.metadata.sorted_tables
        if "available_at" in table.c
    }
    assert set(late.values()) == {0}, late


def test_replay_is_deterministic(tmp_path):
    a, b = _world(tmp_path, "a"), _world(tmp_path, "b")
    replay(a.session, D1, D3, assume_timely=True)
    replay(b.session, D1, D3, assume_timely=True)
    for day in (D1, D2, D3):
        assert _summary(a, day) == _summary(b, day)


def test_strict_replay_waits_for_collection_and_classification(tmp_path):
    late = _world(tmp_path, "late", classified_on=D3)  # D1 글을 D3에 분류했다
    replay(late.session, D1, D2)
    assert _summary(late, D2)[1] == []  # 그때는 분류가 없었다
    timely = _world(tmp_path, "timely", classified_on=D3)
    replay(timely.session, D1, D2, assume_timely=True)
    assert _summary(timely, D2)[1] != []


def test_replay_needs_an_unbuilt_graph(tmp_path):
    g = _world(tmp_path, "built")
    g.build()
    with pytest.raises(ValueError, match="already in the graph"):
        replay(g.session, D1, D2)

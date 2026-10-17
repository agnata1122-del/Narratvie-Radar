"""리빙 위키 (PRD 9장, M6).

- 위키는 DB에 쌓인 사실(관계, 근거, 내러티브, 이벤트)로 만든다. 문장을 지어내지 않는다.
- 섹션마다 내용 지문을 남기고, 하나라도 바뀌었을 때만 새 리비전을 추가한다.
  이전 리비전은 지우지 않는다.
- 시점 t의 위키는 available_at <= t인 마지막 리비전이다.
- 근거에는 짧은 발췌와 링크만 보여주고, 지워진 글은 빼낸다 (DATA_POLICY 10, 12).
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.core.clock import Clock
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import (
    Claim,
    Document,
    EdgeEvidence,
    GraphEvent,
    InterestProfile,
    Narrative,
    NarrativeClaim,
    Node,
    NodeAlias,
    WikiRevision,
)
from narrative_radar.schemas.enums import EdgeType, NarrativeRole
from narrative_radar.temporal.narratives import narrative_state_at
from narrative_radar.temporal.state import GraphState, NodeState, graph_state, neighborhood_state

SCHEMA_VERSION = "wiki.v1"
GENERATOR = "facts.v1"  # LLM 없이 사실로 만든 위키

RELATION_KO = {
    "RELATED_TO": "관련",
    "PART_OF": "일부",
    "BELONGS_TO": "소속",
    "SUPPLIES_TO": "공급",
    "COMPETES_WITH": "경쟁",
    "AFFECTS": "영향",
    "CLAIMED_CAUSE_OF": "원인이라는 주장",
    "CO_MENTIONED_WITH": "함께 언급",
}
TYPE_KO = {
    "organization": "조직",
    "person": "인물",
    "product": "제품·작품",
    "technology": "기술",
    "topic": "주제",
    "event": "사건",
    "place": "장소",
    "narrative": "내러티브",
}
STATUS_KO = {"candidate": "발견 후보", "confirmed": "관측 확정", "weakened": "약해짐"}
STATE_KO = {
    "emerging": "새로 등장",
    "spreading": "확산 중",
    "contested": "논쟁 중",
    "reversed": "논조 반전",
    "fading": "잦아듦",
    "split": "갈라짐",
}


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    markdown: str
    links: list[dict[str, str]]

    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.title}\n{self.markdown}".encode()).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "title": self.title,
            "markdown": self.markdown,
            "links": self.links,
        }


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _link(node: NodeState) -> str:
    return f"[[{node.label}]]"


def _excerpt_lines(session: Session, rows: list[tuple[str, str | None]], limit: int) -> list[str]:
    """(document_id, excerpt) → 지워지지 않은 글만, 최신순."""
    if not rows:
        return []
    excerpts = {d: e for d, e in rows}
    docs = session.scalars(
        sa.select(Document)
        .where(Document.document_id.in_(excerpts), Document.deleted_observed_at.is_(None))
        .order_by(Document.published_at.desc())
        .limit(limit)
    ).all()
    out = []
    for d in docs:
        quote = excerpts.get(d.document_id)
        text = f" — “{quote}”" if quote else ""
        out.append(f"- {d.source} · {_fmt(d.published_at)}{text} ([원문]({d.source_url}))")
    return out


def build_sections(session: Session, state: GraphState, node_id: str) -> list[Section]:
    now = state.as_of
    nodes = {n.node_id: n for n in state.nodes}
    me = nodes[node_id]
    narrative = session.scalar(sa.select(Narrative).where(Narrative.node_id == node_id))
    aliases = sorted(
        set(session.scalars(sa.select(NodeAlias.alias).where(NodeAlias.node_id == node_id)))
        - {me.label}
    )

    sections: list[Section] = []
    status = (
        "휴면" if me.dormant else {"active": "활성", "candidate": "후보"}.get(me.status, me.status)
    )
    overview = [
        f"**{me.label}** · {TYPE_KO.get(me.node_type, me.node_type)} · 상태: {status}",
        f"처음 관측: {_fmt(me.first_seen)} · "
        f"최근 7일 언급 {me.mentions_7d}건 (독립 {me.independent_7d})",
    ]
    if aliases:
        overview.append("다른 표기: " + ", ".join(aliases[:10]))
    if narrative is not None:
        snap = narrative_state_at(session, narrative.narrative_id, now)
        overview.insert(1, f"명제: {narrative.proposition}")
        if snap.state:
            overview.append(
                f"내러티브 상태: {STATE_KO[snap.state.value]} "
                f"(최근 7일 지지 {snap.supports_recent} · 반박 {snap.contradicts_recent})"
            )
    overview.append("커뮤니티에서 관측된 주장을 정리한 것이며 사실 확인을 거치지 않았다.")
    sections.append(Section("overview", "개요", "\n\n".join(overview), []))

    mine = [e for e in state.edges if node_id in (e.source, e.target)]
    semantic = [e for e in mine if e.relation != EdgeType.CO_MENTIONED_WITH]
    related_lines, links = [], []
    for e in semantic[:15]:
        other = nodes.get(e.target if e.source == node_id else e.source)
        if other is None:
            continue
        arrow = "→" if e.source == node_id else "←"
        related_lines.append(
            f"- {arrow} {_link(other)} · {RELATION_KO.get(e.relation, e.relation)} · "
            f"{STATUS_KO.get(e.status, e.status)} (독립 근거 {e.independent_evidence})"
        )
        links.append({"label": other.label, "node_id": other.node_id})
    co = [e for e in mine if e.relation == EdgeType.CO_MENTIONED_WITH][:8]
    co_names = []
    for e in co:
        other = nodes.get(e.target if e.source == node_id else e.source)
        if other is not None:
            co_names.append(_link(other))
            links.append({"label": other.label, "node_id": other.node_id})
    if co_names:
        related_lines.append("- 자주 함께 언급: " + ", ".join(co_names))
    sections.append(Section("related", "관련 대상", "\n".join(related_lines) or "아직 없음", links))

    narrative_lines, n_links = [], []
    narrative_nodes = {
        nid
        for e in semantic
        for nid in (e.source, e.target)
        if nid != node_id and nodes.get(nid) and nodes[nid].node_type == "narrative"
    }
    conflicting: list[str] = []
    for nid in sorted(narrative_nodes, key=lambda x: -nodes[x].activity):
        nar = session.scalar(sa.select(Narrative).where(Narrative.node_id == nid))
        if nar is None:
            continue
        snap = narrative_state_at(session, nar.narrative_id, now)
        state_ko = STATE_KO[snap.state.value] if snap.state else "알 수 없음"
        narrative_lines.append(
            f"- {_link(nodes[nid])} · {state_ko} · "
            f"지지 {snap.supports_recent} / 반박 {snap.contradicts_recent}"
        )
        n_links.append({"label": nodes[nid].label, "node_id": nid})
        if snap.state and snap.state.value in ("contested", "reversed"):
            conflicting.append(nar.narrative_id)
    sections.append(
        Section("narratives", "현재 내러티브", "\n".join(narrative_lines) or "아직 없음", n_links)
    )

    recent_cut = now - timedelta(days=7)
    emerging = [e for e in semantic if e.first_seen > recent_cut]
    em_lines, em_links = [], []
    for e in emerging[:10]:
        other = nodes.get(e.target if e.source == node_id else e.source)
        if other is None:
            continue
        em_lines.append(
            f"- {_link(other)} · {RELATION_KO.get(e.relation, e.relation)} · "
            f"처음 관측 {_fmt(e.first_seen)}"
        )
        em_links.append({"label": other.label, "node_id": other.node_id})
    sections.append(
        Section("emerging", "최근 새로 나온 연결", "\n".join(em_lines) or "없음", em_links)
    )

    conflict_lines = []
    for narrative_id in conflicting:
        nar = session.get_one(Narrative, narrative_id)
        conflict_lines.append(f"**{nar.proposition}**")
        for role, title in ((NarrativeRole.SUPPORTS, "지지"), (NarrativeRole.CONTRADICTS, "반박")):
            rows = session.execute(
                sa.select(Claim.document_id, Claim.excerpt)
                .join(NarrativeClaim, NarrativeClaim.claim_id == Claim.claim_id)
                .where(
                    NarrativeClaim.narrative_id == narrative_id,
                    NarrativeClaim.role == role,
                    NarrativeClaim.available_at <= now,
                )
            ).all()
            lines = _excerpt_lines(session, rows, 2)
            if lines:
                conflict_lines.append(f"{title}:")
                conflict_lines.extend(lines)
    sections.append(
        Section("conflicting", "상충하는 주장", "\n".join(conflict_lines) or "없음", [])
    )

    events = session.scalars(
        sa.select(GraphEvent)
        .where(GraphEvent.node_id == node_id, GraphEvent.available_at <= now)
        .order_by(GraphEvent.available_at.desc())
        .limit(10)
    ).all()
    edge_events = session.scalars(
        sa.select(GraphEvent)
        .where(
            GraphEvent.edge_id.in_([e.edge_id for e in semantic]),
            GraphEvent.available_at <= now,
        )
        .order_by(GraphEvent.available_at.desc())
        .limit(10)
    ).all()
    history = sorted([*events, *edge_events], key=lambda ev: ev.available_at, reverse=True)[:10]
    cause_ko = {
        "observed_new": "새로 관측",
        "backfill": "과거 자료",
        "reprocess": "재분류",
        "source_added": "소스 추가",
        "user_action": "사용자",
    }
    hist_lines = [
        f"- {_fmt(ev.available_at)} · {ev.event_type.value} · "
        f"{cause_ko.get(ev.cause.value, ev.cause.value)}"
        for ev in history
    ]
    sections.append(Section("history", "변화 기록", "\n".join(hist_lines) or "없음", []))

    ev_rows = session.execute(
        sa.select(EdgeEvidence.document_id, Claim.excerpt)
        .outerjoin(Claim, Claim.claim_id == EdgeEvidence.claim_id)
        .where(
            EdgeEvidence.edge_id.in_([e.edge_id for e in semantic]),
            EdgeEvidence.available_at <= now,
        )
    ).all()
    sections.append(
        Section("sources", "근거", "\n".join(_excerpt_lines(session, ev_rows, 8)) or "없음", [])
    )
    return sections


def latest_revision(
    session: Session, node_id: str, as_of: datetime | None = None
) -> WikiRevision | None:
    q = sa.select(WikiRevision).where(WikiRevision.node_id == node_id)
    if as_of is not None:
        q = q.where(WikiRevision.available_at <= as_of)
    return session.scalars(q.order_by(WikiRevision.version.desc())).first()


def refresh_wiki(
    session: Session,
    clock: Clock,
    run_id: str,
    profiles: InterestProfile | Sequence[InterestProfile],
) -> tuple[int, int]:
    """관심사 그래프들에 들어 있는 노드마다 위키를 다시 만들고, 바뀐 것만 새 리비전으로 저장한다.

    위키는 노드 중심이다: 어느 관심사에서 보든 같은 노드는 같은 위키를 쓴다. 내용은 공통 그래프에서
    그 노드의 바로 옆(관측 확정·발견 후보 관계)으로 만든다 (DECISIONS D23).
    """
    now = clock.now()
    if isinstance(profiles, InterestProfile):
        profiles = [profiles]
    node_ids: dict[str, None] = {}
    for profile in profiles:
        for n in graph_state(session, profile, now, include_pending=False).nodes:
            node_ids.setdefault(n.node_id)
    created = unchanged = 0
    for node_id in node_ids:
        state = neighborhood_state(session, session.get_one(Node, node_id), now)
        if not any(n.node_id == node_id for n in state.nodes):
            continue
        node = next(n for n in state.nodes if n.node_id == node_id)
        sections = build_sections(session, state, node.node_id)
        prints = {s.key: s.fingerprint() for s in sections}
        prev = latest_revision(session, node.node_id)
        if prev is not None and prev.section_fingerprints == prints:
            unchanged += 1
            continue
        source_ids = sorted(
            set(
                session.scalars(
                    sa.select(EdgeEvidence.document_id).where(
                        EdgeEvidence.edge_id.in_(
                            [e.edge_id for e in state.edges if node.node_id in (e.source, e.target)]
                        )
                    )
                )
            )
        )[:200]
        session.add(
            WikiRevision(
                revision_id=new_id("wik", now),
                node_id=node.node_id,
                version=(prev.version + 1) if prev else 1,
                sections=[s.to_dict() for s in sections],
                section_fingerprints=prints,
                source_document_ids=source_ids,
                model=GENERATOR,
                prompt_version=None,
                schema_version=SCHEMA_VERSION,
                updated_at=now,
                available_at=now,
                run_id=run_id,
            )
        )
        created += 1
    session.flush()
    return created, unchanged

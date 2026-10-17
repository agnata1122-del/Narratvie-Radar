"""조회 API (M8–M9). 테스터는 미리 계산된 결과를 조회만 한다 (DECISIONS D12, D16).

시점을 받는 모든 조회는 available_at <= 그 시점인 기록만 쓴다. 방문자는 익명 쿠키로 구분하고,
숨김·거절·저장 필터·피드백만 방문자별로 저장한다 (PRD 8.4).
"""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from narrative_radar.core.clock import Clock
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import (
    Claim,
    ClassificationFeedback,
    Document,
    Edge,
    EdgeEvidence,
    GraphEvent,
    InterestProfile,
    Narrative,
    Node,
    SavedView,
    SourceAdapter,
    Viewer,
    ViewerOverlay,
)
from narrative_radar.domains import get_pack
from narrative_radar.schemas.enums import TargetType, ViewerDecision
from narrative_radar.schemas.views import SavedViewIn
from narrative_radar.temporal.changes import observation_gaps, what_changed
from narrative_radar.temporal.narratives import narrative_state_at
from narrative_radar.temporal.state import GraphState, graph_state
from narrative_radar.wiki.build import latest_revision

VISIT_GAP = timedelta(minutes=30)
VIEWER_COOKIE = "nr_viewer"
MAX_FRAMES = 96


def build_router(sessions: sessionmaker[Session], clock: Clock) -> APIRouter:
    router = APIRouter(prefix="/api")

    def db():  # type: ignore[no-untyped-def]
        with sessions() as session:
            yield session

    DB = Annotated[Session, Depends(db)]
    ViewerId = Annotated[str | None, Cookie(alias=VIEWER_COOKIE)]

    def profile(session: Session) -> InterestProfile:
        p = session.scalars(sa.select(InterestProfile).order_by(InterestProfile.created_at)).first()
        if p is None:
            raise HTTPException(503, "no interest profile; run `nr db init`")
        return p

    def known_viewer(session: Session, viewer_id: str | None) -> str | None:
        if viewer_id and session.get(Viewer, viewer_id) is not None:
            return viewer_id
        return None

    def at(value: datetime | None) -> datetime:
        return value.astimezone(UTC) if value else clock.now()

    @router.get("/overview")
    def overview(session: DB, viewer: ViewerId = None) -> dict[str, object]:
        p = profile(session)
        pack = get_pack(p.domain)
        root = session.scalar(sa.select(Node).where(Node.canonical_key == p.root_canonical_key))
        first = session.scalar(sa.select(sa.func.min(GraphEvent.available_at)))
        v = session.get(Viewer, viewer) if viewer else None
        return {
            "profile": {
                "profile_id": p.profile_id,
                "name": p.name,
                "domain": {"id": pack.id, "name": pack.name, "lenses": list(pack.lenses)},
                "root_key": p.root_canonical_key,
                "root_label": root.label if root else p.root_canonical_key,
                "root_node_id": root.node_id if root else None,
                "max_depth": p.max_depth,
                "auto_expand": p.auto_expand,
                "max_new_nodes_per_day": p.max_new_nodes_per_day,
                "minimum_independent_evidence": p.minimum_independent_evidence,
            },
            "sources": [
                {
                    "id": s.source_adapter_id,
                    "display_name": s.display_name,
                    "access_status": s.access_status.value,
                }
                for s in session.scalars(
                    sa.select(SourceAdapter).order_by(SourceAdapter.source_adapter_id)
                )
            ],
            "time": {"start": first, "now": clock.now()},
            "counts": {
                "documents": session.scalar(sa.select(sa.func.count()).select_from(Document)),
                "nodes": session.scalar(sa.select(sa.func.count()).select_from(Node)),
                "edges": session.scalar(sa.select(sa.func.count()).select_from(Edge)),
            },
            "viewer": {"viewer_id": v.viewer_id, "last_seen_at": v.last_seen_at} if v else None,
        }

    @router.post("/viewer/visit")
    def visit(response: Response, session: DB, viewer: ViewerId = None) -> dict[str, object]:
        """방문 기록. "지난 방문 이후"의 기준 시각을 돌려준다.

        VISIT_GAP 안에 다시 열면(새로고침 등) 같은 방문으로 보고 기준 시각을 그대로 둔다.
        """
        now = clock.now()
        v = session.get(Viewer, viewer) if viewer else None
        if v is None:
            v = Viewer(viewer_id=new_id("vwr", now), created_at=now, last_seen_at=now)
            session.add(v)
        else:
            if now - v.last_seen_at >= VISIT_GAP:
                v.previous_seen_at = v.last_seen_at
            v.last_seen_at = now
        previous = v.previous_seen_at
        session.commit()
        response.set_cookie(
            VIEWER_COOKIE, v.viewer_id, max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax"
        )
        return {"viewer_id": v.viewer_id, "previous_seen_at": previous}

    @router.get("/state")
    def state(
        session: DB,
        as_of: AwareDatetime | None = None,
        include_pending: bool = True,
        viewer: ViewerId = None,
    ) -> dict[str, object]:
        t = at(as_of)
        s = graph_state(
            session, profile(session), t, known_viewer(session, viewer), include_pending
        )
        return _state_payload(session, s, t)

    @router.get("/frames")
    def frames(
        session: DB,
        start: AwareDatetime,
        end: AwareDatetime,
        steps: Annotated[int, Query(ge=2, le=MAX_FRAMES)] = 48,
        include_pending: bool = False,
        viewer: ViewerId = None,
    ) -> dict[str, object]:
        """재생용 프레임. 노드·관계 메타데이터는 한 번만 보내고 프레임에는 바뀌는 값만 담는다."""
        if end <= start:
            raise HTTPException(422, "end must be after start")
        p, vid = profile(session), known_viewer(session, viewer)
        step = (end - start) / (steps - 1)
        nodes_meta: dict[str, dict[str, object]] = {}
        edges_meta: dict[str, dict[str, object]] = {}
        out = []
        for i in range(steps):
            t = (start + step * i).astimezone(UTC)
            s = graph_state(session, p, t, vid, include_pending)
            for n in s.nodes:
                nodes_meta.setdefault(
                    n.node_id,
                    {"label": n.label, "type": n.node_type, "key": n.canonical_key},
                )
            for e in s.edges:
                edges_meta.setdefault(
                    e.edge_id, {"source": e.source, "target": e.target, "relation": e.relation}
                )
            out.append(
                {
                    "t": t,
                    "nodes": {
                        n.node_id: [n.activity, n.status, n.membership, n.mentions_7d]
                        for n in s.nodes
                    },
                    "edges": {
                        e.edge_id: [e.strength, e.status, e.independent_evidence] for e in s.edges
                    },
                }
            )
        return {"nodes": nodes_meta, "edges": edges_meta, "frames": out}

    @router.get("/changes")
    def changes(
        session: DB,
        until: AwareDatetime | None = None,
        since: AwareDatetime | None = None,
        viewer: ViewerId = None,
    ) -> dict[str, object]:
        u = at(until)
        s = since.astimezone(UTC) if since else u - timedelta(days=1)
        if s >= u:
            raise HTTPException(422, "since must be before until")
        report = what_changed(session, profile(session), s, u, known_viewer(session, viewer))
        return asdict(report)

    @router.get("/events")
    def events(
        session: DB,
        start: AwareDatetime,
        end: AwareDatetime,
        limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    ) -> list[dict[str, object]]:
        rows = session.scalars(
            sa.select(GraphEvent)
            .where(GraphEvent.available_at >= start, GraphEvent.available_at <= end)
            .order_by(GraphEvent.available_at)
            .limit(limit)
        ).all()
        return [
            {
                "t": e.available_at,
                "type": e.event_type.value,
                "cause": e.cause.value,
                "node_id": e.node_id,
                "edge_id": e.edge_id,
            }
            for e in rows
        ]

    @router.get("/gaps")
    def gaps(session: DB, start: AwareDatetime, end: AwareDatetime) -> list[dict[str, object]]:
        return [asdict(g) for g in observation_gaps(session, start, end)]

    @router.get("/nodes/{node_id}")
    def node_detail(
        node_id: str, session: DB, as_of: AwareDatetime | None = None, viewer: ViewerId = None
    ) -> dict[str, object]:
        t = at(as_of)
        node = session.get(Node, node_id)
        if node is None or node.available_at > t:
            raise HTTPException(404, "node not known at this time")
        s = graph_state(session, profile(session), t, known_viewer(session, viewer))
        me = next((n for n in s.nodes if n.node_id == node_id), None)
        rev = latest_revision(session, node_id, as_of=t)
        narrative = session.scalar(sa.select(Narrative).where(Narrative.node_id == node_id))
        snap = narrative_state_at(session, narrative.narrative_id, t) if narrative else None
        return {
            "node": asdict(me) if me else None,
            "wiki": {
                "version": rev.version,
                "available_at": rev.available_at,
                "generator": rev.model,
                "sections": rev.sections,
            }
            if rev
            else None,
            "narrative": {"proposition": narrative.proposition, **asdict(snap)}
            if narrative and snap
            else None,
        }

    @router.get("/edges/{edge_id}")
    def edge_detail(
        edge_id: str, session: DB, as_of: AwareDatetime | None = None
    ) -> dict[str, object]:
        t = at(as_of)
        edge = session.get(Edge, edge_id)
        if edge is None or edge.available_at > t:
            raise HTTPException(404, "edge not known at this time")
        rows = session.execute(
            sa.select(
                Document, EdgeEvidence.derivation_group_id, Claim.excerpt, Claim.evidence_status
            )
            .join(EdgeEvidence, EdgeEvidence.document_id == Document.document_id)
            .outerjoin(Claim, Claim.claim_id == EdgeEvidence.claim_id)
            .where(EdgeEvidence.edge_id == edge_id, EdgeEvidence.available_at <= t)
            .order_by(Document.published_at.desc())
            .limit(50)
        ).all()
        labels = dict(
            session.execute(
                sa.select(Node.node_id, Node.label).where(
                    Node.node_id.in_([edge.source_node_id, edge.target_node_id])
                )
            ).all()
        )
        return {
            "edge_id": edge.edge_id,
            "source": {"node_id": edge.source_node_id, "label": labels.get(edge.source_node_id)},
            "target": {"node_id": edge.target_node_id, "label": labels.get(edge.target_node_id)},
            "relation": edge.relation_type.value,
            "evidence": [
                {
                    "document_id": d.document_id,
                    "source": d.source,
                    "published_at": d.published_at,
                    "deleted": d.deleted_observed_at is not None,
                    # 지워진 글은 링크와 발췌를 다시 보여주지 않는다 (DATA_POLICY 12)
                    "url": None if d.deleted_observed_at else d.source_url,
                    "excerpt": None if d.deleted_observed_at else excerpt,
                    "evidence_status": status.value if status else None,
                    "derivation_group_id": group,
                }
                for d, group, excerpt, status in rows
            ],
        }

    class OverlayIn(BaseModel):
        target_id: str
        decision: Literal["approved", "rejected", "hidden"]

    @router.post("/overlays")
    def set_overlay(body: OverlayIn, session: DB, viewer: ViewerId = None) -> dict[str, str]:
        vid = known_viewer(session, viewer)
        if vid is None:
            raise HTTPException(401, "visit first: POST /api/viewer/visit")
        p = profile(session)
        existing = session.get(ViewerOverlay, (vid, p.profile_id, TargetType.NODE, body.target_id))
        if existing is None:
            session.add(
                ViewerOverlay(
                    viewer_id=vid,
                    profile_id=p.profile_id,
                    target_type=TargetType.NODE,
                    target_id=body.target_id,
                    decision=ViewerDecision(body.decision),
                    created_at=clock.now(),
                )
            )
        else:
            existing.decision = ViewerDecision(body.decision)
        session.commit()
        return {"status": "ok"}

    @router.delete("/overlays/{target_id}")
    def clear_overlay(target_id: str, session: DB, viewer: ViewerId = None) -> dict[str, str]:
        vid = known_viewer(session, viewer)
        if vid is None:
            raise HTTPException(401, "visit first")
        p = profile(session)
        existing = session.get(ViewerOverlay, (vid, p.profile_id, TargetType.NODE, target_id))
        if existing is not None:
            session.delete(existing)
            session.commit()
        return {"status": "ok"}

    @router.get("/views")
    def list_views(session: DB, viewer: ViewerId = None) -> list[dict[str, object]]:
        vid = known_viewer(session, viewer)
        rows = session.scalars(
            sa.select(SavedView).where(SavedView.viewer_id == vid).order_by(SavedView.created_at)
        ).all()
        return [{"view_id": v.view_id, "name": v.name, "filters": v.filters} for v in rows]

    @router.post("/views")
    def save_view(body: SavedViewIn, session: DB, viewer: ViewerId = None) -> dict[str, str]:
        vid = known_viewer(session, viewer)
        if vid is None:
            raise HTTPException(401, "visit first")
        now = clock.now()
        view = SavedView(
            view_id=new_id("vew", now),
            viewer_id=vid,
            profile_id=profile(session).profile_id,
            name=body.view_name,
            filters=body.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
        session.add(view)
        session.commit()
        return {"view_id": view.view_id}

    class FeedbackIn(BaseModel):
        target_type: Literal["node", "edge", "claim", "narrative", "classification", "wiki"]
        target_id: str
        rating: Annotated[int, Field(ge=-1, le=1)] | None = None
        label: str | None = Field(default=None, max_length=100)
        comment: str | None = Field(default=None, max_length=2000)

    @router.post("/feedback")
    def feedback(body: FeedbackIn, session: DB, viewer: ViewerId = None) -> dict[str, str]:
        vid = known_viewer(session, viewer)
        now = clock.now()
        session.add(
            ClassificationFeedback(
                feedback_id=new_id("fbk", now),
                viewer_id=vid,
                target_type=TargetType(body.target_type),
                target_id=body.target_id,
                rating=body.rating,
                label=body.label,
                comment=body.comment,
                created_at=now,
            )
        )
        session.commit()
        return {"status": "ok"}

    return router


def _state_payload(session: Session, s: GraphState, t: datetime) -> dict[str, object]:
    narrative_of = dict(
        session.execute(
            sa.select(Narrative.node_id, Narrative.narrative_id).where(
                Narrative.node_id.in_([n.node_id for n in s.nodes])
            )
        ).all()
    )
    narratives = {}
    for node_id, narrative_id in narrative_of.items():
        snap = narrative_state_at(session, narrative_id, t)
        narratives[node_id] = {
            "state": snap.state.value if snap.state else None,
            "supports": snap.supports_recent,
            "contradicts": snap.contradicts_recent,
        }
    payload = asdict(s)
    payload["narratives"] = narratives
    return payload

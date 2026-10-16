"""시점 t의 내러티브 상태 (DECISIONS D5).

최근 7일(게시 시각 기준, available_at <= t인 것만)과 그 전 7일의 지지·반박 주장을
복사 묶음 단위로 센다.

- emerging: 처음 나온 지 7일 안이고 아직 작다(3묶음 이하)
- spreading: 최근이 이전의 2배 이상이고 3묶음 이상
- contested: 최근에 지지·반박이 둘 다 2묶음 이상이고, 반박이 1/3 이상
- reversed: 이전에는 지지(또는 반박)가 다수였는데 최근에는 반대가 다수이고, 최근이 3묶음 이상
- fading: 최근 7일에 주장이 없다
- 그 밖: 최근이 이전보다 많으면 spreading, 아니면 fading
- split(갈라짐)은 군집 분석이 필요해 P1로 미룬다 (DECISIONS D14)
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.db.models import Claim, Document, Narrative, NarrativeClaim
from narrative_radar.schemas.enums import NarrativeRole, NarrativeState

WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class NarrativeSnapshot:
    narrative_id: str
    state: NarrativeState | None  # None: 아직 알려지지 않음
    supports_recent: int
    contradicts_recent: int
    supports_previous: int
    contradicts_previous: int
    first_seen: datetime | None


def narrative_state_at(session: Session, narrative_id: str, as_of: datetime) -> NarrativeSnapshot:
    rows = session.execute(
        sa.select(
            NarrativeClaim.claim_id,
            NarrativeClaim.role,
            NarrativeClaim.available_at,
            Document.published_at,
            Document.derivation_group_id,
            Document.document_id,
        )
        .join(Claim, Claim.claim_id == NarrativeClaim.claim_id)
        .join(Document, Document.document_id == Claim.document_id)
        .where(NarrativeClaim.narrative_id == narrative_id, NarrativeClaim.available_at <= as_of)
        .order_by(NarrativeClaim.available_at, NarrativeClaim.assignment_id)
    ).all()
    # 주장마다 마지막 배정만 쓴다 (다른 내러티브로 옮겨 가면 detached)
    latest: dict[str, tuple[NarrativeRole, datetime, str]] = {}
    for claim_id, role, _, published_at, group, doc_id in rows:
        latest[claim_id] = (role, published_at, group or f"doc:{doc_id}")

    def groups(role: NarrativeRole, start: datetime, end: datetime) -> int:
        return len({g for r, p, g in latest.values() if r == role and start < p <= end})

    recent_start, prev_start = as_of - WINDOW, as_of - 2 * WINDOW
    s_r = groups(NarrativeRole.SUPPORTS, recent_start, as_of)
    c_r = groups(NarrativeRole.CONTRADICTS, recent_start, as_of)
    s_p = groups(NarrativeRole.SUPPORTS, prev_start, recent_start)
    c_p = groups(NarrativeRole.CONTRADICTS, prev_start, recent_start)
    published = [p for r, p, _ in latest.values() if r != NarrativeRole.DETACHED and p <= as_of]
    first = min(published, default=None)
    return NarrativeSnapshot(
        narrative_id, _classify(s_r, c_r, s_p, c_p, first, as_of), s_r, c_r, s_p, c_p, first
    )


def _classify(
    s_r: int, c_r: int, s_p: int, c_p: int, first: datetime | None, as_of: datetime
) -> NarrativeState | None:
    if first is None:
        return None
    recent, previous = s_r + c_r, s_p + c_p
    if recent == 0:
        return NarrativeState.FADING
    if recent >= 3 and previous >= 2:
        before_support = s_p > c_p
        now_support = s_r > c_r
        if before_support != now_support and s_p != c_p and s_r != c_r:
            return NarrativeState.REVERSED
    if s_r >= 2 and c_r >= 2 and c_r * 3 >= recent:
        return NarrativeState.CONTESTED
    if recent >= 3 and recent >= 2 * max(previous, 1):
        return NarrativeState.SPREADING
    if as_of - first <= WINDOW and recent <= 3:
        return NarrativeState.EMERGING
    return NarrativeState.SPREADING if recent > previous else NarrativeState.FADING


def narratives_for_nodes(session: Session, node_ids: set[str]) -> dict[str, str]:
    """내러티브 노드 ID → narrative_id."""
    return dict(
        session.execute(
            sa.select(Narrative.node_id, Narrative.narrative_id).where(
                Narrative.node_id.in_(node_ids)
            )
        ).all()
    )

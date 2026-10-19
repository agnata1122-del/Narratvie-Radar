"""관계의 근거 단계 계산 (DECISIONS D34, D39).

그래프의 `confirmed`(D6: 독립 출처 2곳 이상)는 바꾸지 않고, 근거 주장의 성격(`evidence_status`)으로
사실 확인 / 반복 관측 / 탐색 가설을 나눈다. 사실을 검증하는 것이 아니라 근거가 어떤 종류인지 보인다.
"""

from collections import defaultdict
from collections.abc import Collection
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.db.models import Claim, Edge, EdgeEvidence
from narrative_radar.schemas.enums import EdgeStatus, EvidenceStatus, EvidenceTier

TIER_RANK = {EvidenceTier.SOURCED: 2, EvidenceTier.REPEATED: 1, EvidenceTier.HYPOTHESIS: 0}
REPORTED = frozenset({EvidenceStatus.REPORTED_FACT, EvidenceStatus.OFFICIAL_SOURCE})


def _independent(rows: list[tuple[str | None, str | None, str]]) -> int:
    """서로 다른 복사 묶음이면서 서로 다른 작성자인 근거 수.

    builder.independent_evidence와 같은 셈이다."""
    groups = {g or f"doc:{d}" for g, _, d in rows}
    authors = {a or f"doc:{d}" for _, a, d in rows}
    return min(len(groups), len(authors))


def edge_tiers(
    session: Session, edge_ids: Collection[str] | None = None, as_of: datetime | None = None
) -> dict[str, EvidenceTier]:
    """관계마다 근거 단계. 주장 없이 공동 언급만 있는 관계는 탐색 가설이다.

    as_of를 주면 그 시점의 확정 여부와 근거만 본다 (미래 정보를 섞지 않는다)."""
    edges = sa.select(Edge.edge_id, Edge.status)
    if edge_ids is not None:
        edges = edges.where(Edge.edge_id.in_(list(edge_ids)))
    status = dict(session.execute(edges).all())
    if as_of is not None:
        from narrative_radar.temporal.state import edge_statuses_at

        status = edge_statuses_at(session, set(status), as_of)
    q = (
        sa.select(
            EdgeEvidence.edge_id,
            EdgeEvidence.derivation_group_id,
            EdgeEvidence.author_hash,
            EdgeEvidence.document_id,
            Claim.evidence_status,
        )
        .outerjoin(Claim, Claim.claim_id == EdgeEvidence.claim_id)
        .where(EdgeEvidence.edge_id.in_(list(status)))
    )
    if as_of is not None:
        q = q.where(EdgeEvidence.available_at <= as_of)
    by_edge: dict[str, list[tuple]] = defaultdict(list)
    for edge_id, group, author, doc, ev in session.execute(q):
        by_edge[edge_id].append((group, author, doc, ev))

    tiers = {}
    for edge_id, st in status.items():
        rows = by_edge.get(edge_id, [])
        kinds = {ev for *_, ev in rows if ev is not None}
        if st != EdgeStatus.CONFIRMED or not kinds or kinds == {EvidenceStatus.SPECULATION}:
            tiers[edge_id] = EvidenceTier.HYPOTHESIS
            continue
        reported = [(g, a, d) for g, a, d, ev in rows if ev in REPORTED]
        official = any(ev == EvidenceStatus.OFFICIAL_SOURCE for *_, ev in rows)
        sourced = official or _independent(reported) >= 2
        tiers[edge_id] = EvidenceTier.SOURCED if sourced else EvidenceTier.REPEATED
    return tiers

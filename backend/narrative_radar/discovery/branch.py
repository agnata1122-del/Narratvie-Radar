"""가지: 관심사 그래프의 노드에서 파고들어 그 노드를 루트로 하는 새 관심사를 만든다 (DECISIONS D23).

- 공통 그래프는 모든 관심사가 함께 쓴다. 가지는 부모가 이미 모은 만큼은 바로 보이고,
  그때부터 자기 루트 기준으로 자란다 (자동 확장 + 수집 검색어).
- 같은 노드를 루트로 하는 관심사가 이미 있으면 새로 만들지 않고 그것을 돌려준다.
- 수집이 폭주하지 않게 관심사 수와 가지 깊이에 상한을 둔다.
"""

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.core.clock import Clock
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import InterestProfile, Node, ProfileNode
from narrative_radar.discovery.expansion import expand_profile
from narrative_radar.ingest.runs import finish_run, start_run
from narrative_radar.schemas.enums import (
    NodeStatus,
    ProfileNodeStatus,
    ProfileOrigin,
    RunKind,
    RunStatus,
)

MAX_PROFILES = 30
MAX_BRANCH_DEPTH = 6  # 루트 관심사에서 가지를 따라 내려간 단계 수


class BranchError(ValueError):
    pass


@dataclass(frozen=True)
class BranchResult:
    profile: InterestProfile
    created: bool


def lineage(session: Session, profile: InterestProfile) -> list[InterestProfile]:
    """루트 관심사부터 이 관심사까지 (경로 표시용). 고리가 생겨도 멈춘다."""
    chain = [profile]
    seen = {profile.profile_id}
    while chain[0].parent_profile_id and chain[0].parent_profile_id not in seen:
        parent = session.get(InterestProfile, chain[0].parent_profile_id)
        if parent is None:
            break
        seen.add(parent.profile_id)
        chain.insert(0, parent)
    return chain


def create_branch(
    session: Session,
    clock: Clock,
    parent: InterestProfile,
    node_id: str,
    max_profiles: int = MAX_PROFILES,
    max_depth: int = MAX_BRANCH_DEPTH,
) -> BranchResult:
    node = session.get(Node, node_id)
    if node is None or node.available_at > clock.now():
        raise BranchError("node not found")
    if node.status in (NodeStatus.REJECTED, NodeStatus.MERGED):
        raise BranchError(f"node is {node.status.value}")

    existing = session.scalar(
        sa.select(InterestProfile).where(InterestProfile.root_canonical_key == node.canonical_key)
    )
    if existing is not None:
        return BranchResult(existing, False)

    if len(lineage(session, parent)) >= max_depth:
        raise BranchError(f"branches can be at most {max_depth} levels deep")
    count = session.scalar(sa.select(sa.func.count()).select_from(InterestProfile)) or 0
    if count >= max_profiles:
        raise BranchError(f"at most {max_profiles} interests")

    now = clock.now()
    run = start_run(
        session,
        clock,
        RunKind.SETUP,
        params={"branch_of": parent.profile_id, "root": node.canonical_key},
    )
    profile = InterestProfile(
        profile_id=new_id("prf", now),
        name=node.label,
        domain=parent.domain,
        parent_profile_id=parent.profile_id,
        origin=ProfileOrigin.BRANCH,
        root_canonical_key=node.canonical_key,
        max_depth=parent.max_depth,
        auto_expand=parent.auto_expand,
        max_new_nodes_per_day=parent.max_new_nodes_per_day,
        minimum_independent_evidence=parent.minimum_independent_evidence,
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    session.flush()
    session.add(
        ProfileNode(
            decision_id=new_id("pnd", now),
            profile_id=profile.profile_id,
            node_id=node.node_id,
            status=ProfileNodeStatus.ADMITTED,
            depth=0,
            reason=f"branch root (from {parent.name})",
            available_at=now,
            run_id=run.run_id,
        )
    )
    session.flush()
    # 이미 관측 확정된 주변은 한 번에 담는다. 그 뒤로는 하루 예산 안에서 자란다.
    expand_profile(session, clock, run.run_id, profile, ignore_budget=True)
    finish_run(run, clock.now(), RunStatus.SUCCEEDED)
    return BranchResult(profile, True)

"""초기 데이터: 소스 등록(수집 꺼짐), 기본 관심사(NVIDIA), 루트 노드.

여러 번 실행해도 결과가 같다.
"""

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar import __version__
from narrative_radar.core.clock import Clock
from narrative_radar.core.ids import new_id
from narrative_radar.core.sources import DEFAULT_SOURCES
from narrative_radar.db.models import (
    GraphEvent,
    InterestProfile,
    Node,
    NodeAlias,
    PipelineRun,
    ProfileNode,
    SourceAdapter,
)
from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas.enums import (
    AliasOrigin,
    EventCause,
    EventType,
    NodeStatus,
    NodeType,
    ProfileNodeStatus,
    RunKind,
    RunMode,
    RunStatus,
    SourceAccessStatus,
)


@dataclass(frozen=True)
class RootInterest:
    profile_name: str
    canonical_key: str
    label: str
    node_type: NodeType
    aliases: tuple[str, ...]


# 은어는 실제 데이터에서 확인하며 추가한다 (DECISIONS D4). 여기에는 확실한 표기만 둔다.
DEFAULT_ROOT = RootInterest(
    profile_name="NVIDIA Research",
    canonical_key="US:NVDA",
    label="NVIDIA",
    node_type=NodeType.COMPANY,
    aliases=("NVIDIA", "NVDA", "엔비디아", "NVIDIA Corporation"),
)


def seed_defaults(session: Session, clock: Clock, root: RootInterest = DEFAULT_ROOT) -> None:
    now = clock.now()
    _seed_sources(session, now)
    if session.scalar(sa.select(Node).where(Node.canonical_key == root.canonical_key)):
        return

    run = PipelineRun(
        run_id=new_id("run", now),
        kind=RunKind.SETUP,
        mode=RunMode.LIVE,
        status=RunStatus.SUCCEEDED,
        started_at=now,
        finished_at=now,
        code_version=__version__,
        params={"root": root.canonical_key},
    )
    # 관계(relationship)를 정의하지 않았으므로 FK 순서대로 직접 flush한다.
    session.add(run)
    session.flush()
    profile = InterestProfile(
        profile_id=new_id("prf", now),
        name=root.profile_name,
        root_canonical_key=root.canonical_key,
        created_at=now,
        updated_at=now,
    )
    node = Node(
        node_id=new_id("nod", now),
        canonical_key=root.canonical_key,
        node_type=root.node_type,
        label=root.label,
        status=NodeStatus.ACTIVE,
        created_at=now,
        available_at=now,
        created_run_id=run.run_id,
    )
    session.add_all([profile, node])
    session.flush()

    seen: set[str] = set()
    for alias in root.aliases:
        key = normalize_text(alias)
        if key in seen:
            continue
        seen.add(key)
        session.add(
            NodeAlias(
                alias_id=new_id("als", now),
                node_id=node.node_id,
                alias=alias,
                alias_normalized=key,
                origin=AliasOrigin.SEED,
                created_at=now,
                available_at=now,
            )
        )
    session.add_all(
        [
            GraphEvent(
                event_id=new_id("evt", now),
                event_type=EventType.NODE_CREATED,
                cause=EventCause.USER_ACTION,
                node_id=node.node_id,
                payload={"reason": "root interest registered"},
                recorded_at=now,
                available_at=now,
                run_id=run.run_id,
            ),
            ProfileNode(
                decision_id=new_id("pnd", now),
                profile_id=profile.profile_id,
                node_id=node.node_id,
                status=ProfileNodeStatus.ADMITTED,
                depth=0,
                reason="root interest",
                available_at=now,
                run_id=run.run_id,
            ),
        ]
    )


def _seed_sources(session: Session, now: datetime) -> None:
    existing = set(session.scalars(sa.select(SourceAdapter.source_adapter_id)))
    for s in DEFAULT_SOURCES:
        if s.id in existing:
            continue
        session.add(
            SourceAdapter(
                source_adapter_id=s.id,
                source=s.source,
                kind=s.kind,
                display_name=s.display_name,
                base_url=s.base_url,
                access_status=SourceAccessStatus.NOT_AUTHORIZED,
                live_enabled=False,
                status_reason="nr sources enable로 켜기 전까지 수집하지 않음 (docs/DATA_POLICY.md)",
                config={},
                updated_at=now,
            )
        )

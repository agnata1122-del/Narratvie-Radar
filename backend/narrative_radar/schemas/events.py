from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict

from narrative_radar.schemas.enums import EdgeType, EventCause, EventType


class GraphEventOut(BaseModel):
    """그래프 변화 이벤트 (PRD 10.2 + 변화 원인, DECISIONS D7)."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: EventType
    cause: EventCause
    node_id: str | None = None
    edge_id: str | None = None
    narrative_id: str | None = None
    source_node: str | None = None
    target_node: str | None = None
    relation_type: EdgeType | None = None
    event_time: AwareDatetime | None = None
    recorded_at: AwareDatetime
    available_at: AwareDatetime
    evidence_ids: list[str]
    run_id: str
    payload: dict[str, Any]

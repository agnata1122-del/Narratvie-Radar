from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ViewFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_range: Literal["24h", "3d", "7d", "30d", "all"] = "7d"
    new_nodes_only: bool = False
    min_relevance: float = Field(default=0.0, ge=0, le=1)
    node_types: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class SavedViewIn(BaseModel):
    """저장된 필터 조합 (PRD 13.3). 매매 전략과는 별개 객체다 (PRD 13.4)."""

    model_config = ConfigDict(extra="forbid")

    view_name: str = Field(min_length=1, max_length=200)
    interest: str
    depth: int = Field(default=2, ge=0, le=3)
    sources: list[str] = Field(default_factory=list)
    filters: ViewFilters = Field(default_factory=ViewFilters)

from pydantic import BaseModel, ConfigDict, Field


class DiscoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_new_nodes_per_day: int = Field(default=15, ge=0)
    minimum_independent_evidence: int = Field(default=2, ge=1)
    require_relevance: bool = True
    allow_depth_overflow: bool = False


class InterestProfileConfig(BaseModel):
    """관심사 설정 (PRD 8.1)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    root_interest: str
    root_canonical_key: str
    max_depth: int = Field(default=2, ge=0, le=3)
    auto_expand: bool = True
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)

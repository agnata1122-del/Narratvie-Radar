from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from narrative_radar.schemas.document import DocumentIn, MetricsIn


@dataclass(frozen=True)
class PollResult:
    documents: list[DocumentIn]
    # 다음 폴링에서 이 시각 이후만 요청한다. 출처가 주는 시각 기준.
    newest_published_at: datetime | None
    queries: int = 0


@dataclass(frozen=True)
class Revisit:
    """지표 스냅샷 재방문 결과. 지워진 글이면 deleted=True."""

    external_id: str
    observed_at: datetime
    metrics: MetricsIn | None = None
    deleted: bool = False
    notes: list[str] = field(default_factory=list)


class PollingCollector(Protocol):
    """소스별 수집기가 구현한다.

    - 모든 HTTP 요청은 PoliteClient를 거쳐야 한다.
    - 응답 구조가 예상과 다르면(파싱 실패) 추측해서 채우지 말고
      `client.guard.trip(TripKind.ERROR, ...)`로 수집을 멈춘다.
    """

    source_adapter_id: str
    parser_version: str

    def poll(self, since: datetime | None) -> PollResult:
        """since 이후에 올라온 관련 글."""
        ...

    def revisit(self, external_id: str) -> Revisit:
        """댓글·추천 수 같은 지표와 삭제 여부를 다시 확인한다 (DECISIONS D2)."""
        ...

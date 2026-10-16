from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from narrative_radar.schemas.document import DocumentIn, MetricsIn


@dataclass(frozen=True)
class ListingItem:
    """목록 페이지에서 본 글 하나. 본문은 fetch_document로 따로 읽는다."""

    external_id: str
    url: str
    title: str
    published_at: datetime | None
    metrics: MetricsIn | None


class Collector(Protocol):
    """소스별 어댑터가 구현한다.

    - 모든 HTTP 요청은 PoliteClient를 거쳐야 한다.
    - 페이지 구조가 예상과 다르면(파싱 실패) 추측해서 채우지 말고
      `client.guard.trip(TripKind.ERROR, ...)`로 수집을 멈춘다.
    """

    source_adapter_id: str
    parser_version: str

    def list_recent(self) -> list[ListingItem]:
        """최신 글 목록 첫 페이지."""
        ...

    def fetch_document(self, item: ListingItem) -> DocumentIn:
        """본문과 댓글, 그 시점의 지표."""
        ...

    def fetch_metrics(self, item: ListingItem) -> MetricsIn:
        """지표 스냅샷 재방문용 (D2)."""
        ...

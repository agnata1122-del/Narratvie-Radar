"""과거 시점 재생 (R2, DECISIONS D41).

하루씩 시계를 그날 끝으로 두고, 그때까지 알 수 있던 글만 그래프에 반영하고 자동 확장을 돌린다.
그래서 재생한 그래프의 기록은 모두 available_at이 그날 끝 이하이고,
읽기 쪽 as_of로 그날 상태를 본다.

- 재생은 아무 글도 반영되지 않은 그래프에서 시작한다 (이미 반영된 글이 있으면 거부한다).
- 실행 기록은 사후 재구성(retrospective)으로 남긴다. 포워드 성과와 섞지 않는다 (D7).
- assume_timely: 나중에 모은 과거 글을 게시 시각에 수집·분류했다고 본다. 이때 분류 결과에는
  그 뒤에 만든 모델·지침이 쓰였으므로 완전한 당시 재현은 아니다.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.core.clock import FixedClock
from narrative_radar.db.models import Document, InterestProfile
from narrative_radar.discovery.expansion import expand_profile
from narrative_radar.graph.builder import GraphBuilder
from narrative_radar.ingest.runs import finish_run, start_run
from narrative_radar.schemas.enums import RunKind, RunMode, RunStatus

BATCH = 1000


@dataclass
class DayReport:
    day: date
    as_of: datetime
    documents: int
    applied: int
    admitted: int
    pending: int


def end_of_day(day: date) -> datetime:
    return datetime.combine(day, time.max, tzinfo=UTC)


def already_built(session: Session) -> int:
    return (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(Document)
            .where(Document.processed_at.is_not(None))
        )
        or 0
    )


def replay(
    session: Session,
    start: date,
    end: date,
    *,
    assume_timely: bool = False,
    min_relevance: float = 0.3,
) -> list[DayReport]:
    if end < start:
        raise ValueError("end is before start")
    if built := already_built(session):
        raise ValueError(f"{built} documents are already in the graph; replay needs a fresh graph")
    profiles = session.scalars(sa.select(InterestProfile)).all()
    min_evidence = min((p.minimum_independent_evidence for p in profiles), default=2)
    reports = []
    day = start
    while day <= end:
        as_of = end_of_day(day)
        clock = FixedClock(as_of)
        run = start_run(
            session,
            clock,
            RunKind.BUILD,
            mode=RunMode.RETROSPECTIVE,
            params={"replay_as_of": as_of.isoformat(), "assume_timely": assume_timely},
        )
        builder = GraphBuilder(
            session,
            clock,
            run.run_id,
            min_relevance=min_relevance,
            min_independent_evidence=min_evidence,
            as_of=as_of,
            assume_timely=assume_timely,
        )
        documents = applied = 0
        while batch := builder.build(BATCH):
            documents += len(batch)
            applied += sum(r.skipped is None for r in batch)
        admitted = pending = 0
        for p in profiles:
            e = expand_profile(session, clock, run.run_id, p)
            admitted += len(e.admitted)
            pending += len(e.pending)
        finish_run(run, clock.now(), RunStatus.SUCCEEDED)
        reports.append(DayReport(day, as_of, documents, applied, admitted, pending))
        day += timedelta(days=1)
    return reports

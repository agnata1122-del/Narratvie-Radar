from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from narrative_radar import __version__
from narrative_radar.core.clock import Clock
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import PipelineRun
from narrative_radar.schemas.enums import RunKind, RunMode, RunStatus


def start_run(
    session: Session,
    clock: Clock,
    kind: RunKind,
    mode: RunMode = RunMode.LIVE,
    params: dict[str, Any] | None = None,
    **versions: str | None,
) -> PipelineRun:
    now = clock.now()
    run = PipelineRun(
        run_id=new_id("run", now),
        kind=kind,
        mode=mode,
        status=RunStatus.RUNNING,
        started_at=now,
        code_version=__version__,
        params=params or {},
        **versions,
    )
    session.add(run)
    session.flush()
    return run


def finish_run(run: PipelineRun, at: datetime, status: RunStatus, error: str | None = None) -> None:
    run.status = status
    run.finished_at = at
    run.error = error

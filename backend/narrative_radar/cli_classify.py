"""`nr classify …`: 세션 분류 흐름 (DECISIONS D16, D22, classifiers/guidelines/)."""

from pathlib import Path

import typer

from narrative_radar.core.config import get_settings

classify_app = typer.Typer(help="분류 (세션 분류 · 규칙 기반 기준선)", no_args_is_help=True)


def _sessions():  # type: ignore[no-untyped-def]
    from narrative_radar.db.session import make_engine, make_session_factory

    return make_session_factory(make_engine(get_settings().database_url))


DOMAIN_OPTION = typer.Option(None, help="도메인 팩 ID. 비우면 관심사에 설정된 팩을 쓴다")


def _pack(session, domain: str | None):  # type: ignore[no-untyped-def]
    """분류에 쓸 도메인 팩. 관심사들이 서로 다른 팩을 쓰면 --domain으로 고른다."""
    import sqlalchemy as sa

    from narrative_radar.db.models import InterestProfile
    from narrative_radar.domains import get_pack, pack_for_profiles

    if domain:
        return get_pack(domain)
    try:
        return pack_for_profiles(session.scalars(sa.select(InterestProfile.domain)))
    except ValueError as e:
        raise typer.BadParameter(str(e)) from None


@classify_app.command("pending")
def classify_pending(
    limit: int = typer.Option(50, min=1, max=500, help="한 번에 내보낼 글 수"),
    out_dir: Path = typer.Option(Path("data/work/classify"), help="내보낼 폴더"),
    domain: str | None = DOMAIN_OPTION,
) -> None:
    """분류할 글(batch.jsonl)과 온톨로지·지침(context.json)을 내보낸다."""
    from narrative_radar.classifiers.session import export_batch, guidelines_for
    from narrative_radar.core.clock import SystemClock

    with _sessions()() as session:
        pack = _pack(session, domain)
        batch, context, n = export_batch(session, SystemClock(), limit, out_dir, pack)
    typer.echo(f"domain: {pack.id} ({pack.name})")
    typer.echo(f"{n} documents → {batch}")
    typer.echo(f"context → {context}")
    for g in guidelines_for(pack):
        typer.echo(f"guidelines → {g}")
    if n:
        typer.echo(f"결과는 {out_dir / 'out.jsonl'}에 쓰고 `nr classify ingest`를 실행한다.")


@classify_app.command("ingest")
def classify_ingest(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, help="분류 결과 JSONL"),
    model: str = typer.Option(..., help="분류한 세션의 모델 이름 (기록용)"),
    domain: str | None = DOMAIN_OPTION,
) -> None:
    """세션이 쓴 분류 결과를 검증해 저장한다. 오류가 난 줄은 고쳐서 다시 넣는다."""
    from narrative_radar.classifiers.session import ingest_records, prompt_version_for
    from narrative_radar.core.clock import SystemClock
    from narrative_radar.ingest.runs import finish_run, start_run
    from narrative_radar.schemas.classification import SCHEMA_VERSION
    from narrative_radar.schemas.enums import RunKind, RunStatus

    clock = SystemClock()
    factory = _sessions()
    with factory.begin() as session:
        prompt_version = prompt_version_for(_pack(session, domain))
        run = start_run(
            session,
            clock,
            RunKind.CLASSIFY,
            params={"file": str(path)},
            model=model,
            prompt_version=prompt_version,
            schema_version=SCHEMA_VERSION,
        )
        with path.open(encoding="utf-8") as f:
            report = ingest_records(session, clock, f, model, run.run_id, prompt_version)
        finish_run(run, clock.now(), RunStatus.SUCCEEDED)
    typer.echo(
        f"accepted={report.accepted} review={report.review} errors={len(report.errors)} "
        f"stale={report.stale} duplicates={report.duplicates}"
    )
    for e in report.errors:
        typer.echo(f"  {e}")
    if report.errors:
        raise typer.Exit(code=1)


@classify_app.command("baseline")
def classify_baseline(limit: int = typer.Option(1000, min=1)) -> None:
    """규칙 기반 기준 분류기로 대기 중인 글을 분류한다 (별칭 일치만, 주장 없음)."""
    import sqlalchemy as sa

    from narrative_radar.classifiers import rule_based
    from narrative_radar.classifiers.session import run_baseline
    from narrative_radar.core.clock import SystemClock
    from narrative_radar.db.models import InterestProfile
    from narrative_radar.ingest.runs import finish_run, start_run
    from narrative_radar.schemas.classification import SCHEMA_VERSION
    from narrative_radar.schemas.enums import RunKind, RunStatus

    clock = SystemClock()
    with _sessions().begin() as session:
        root = session.scalars(sa.select(InterestProfile.root_canonical_key)).first()
        if root is None:
            typer.echo("관심사가 없습니다. `nr db init`을 먼저 실행하세요.")
            raise typer.Exit(code=2)
        run = start_run(
            session,
            clock,
            RunKind.CLASSIFY,
            params={"classifier": rule_based.MODEL_LABEL},
            model=rule_based.MODEL_LABEL,
            prompt_version=rule_based.MODEL_LABEL,
            schema_version=SCHEMA_VERSION,
        )
        n = run_baseline(session, clock, run.run_id, root, limit)
        finish_run(run, clock.now(), RunStatus.SUCCEEDED)
    typer.echo(f"classified {n} documents with {rule_based.MODEL_LABEL}")

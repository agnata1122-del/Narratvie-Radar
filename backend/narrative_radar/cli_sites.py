"""`nr sites …`: 사이트별 수집 허용 상태 (DECISIONS D25, DATA_POLICY 3-1)."""

import typer

from narrative_radar.cli_collect import _context

sites_app = typer.Typer(help="사이트별 수집 허용 상태", no_args_is_help=True)


@sites_app.command("list")
def sites_list(
    status: str | None = typer.Option(None, help="pending_review | allowed | denied | blocked"),
) -> None:
    """사이트 정책과 기다리는 후보 수."""
    import sqlalchemy as sa

    from narrative_radar.collectors.sites import list_policies
    from narrative_radar.db.models import DiscoveredUrl
    from narrative_radar.schemas.enums import CandidateStatus, SitePolicyStatus

    ctx = _context("web")
    with ctx.sessions() as session:
        waiting = dict(
            session.execute(
                sa.select(DiscoveredUrl.domain, sa.func.count())
                .where(DiscoveredUrl.status == CandidateStatus.NEW)
                .group_by(DiscoveredUrl.domain)
            ).all()
        )
        for p in list_policies(session, SitePolicyStatus(status) if status else None):
            typer.echo(
                f"{p.status.value:<15} {p.domain:<40} waiting={waiting.get(p.domain, 0):<4} "
                f"daily_limit={p.daily_limit:<3} {p.decided_by}: {p.reason or ''}"
            )


def _set(site: str, status, reason: str, daily_limit: int | None = None) -> None:  # type: ignore[no-untyped-def]
    from narrative_radar.collectors.sites import set_policy

    ctx = _context("web")
    try:
        with ctx.sessions.begin() as session:
            set_policy(session, ctx.clock, site, status, reason, "owner", daily_limit)
    except ValueError as e:
        typer.echo(str(e))
        raise typer.Exit(code=2) from e
    typer.echo(f"{site}: {status.value}")


@sites_app.command("allow")
def sites_allow(
    site: str,
    reason: str = typer.Option(..., help="허용 근거 (이용 조건·robots.txt를 확인한 내용)"),
    daily_limit: int | None = typer.Option(None, min=1, max=500, help="하루 수집 상한"),
) -> None:
    """사이트를 허용한다. 약관이 자동 수집을 금지하는 사이트는 허용할 수 없다."""
    from narrative_radar.schemas.enums import SitePolicyStatus

    _set(site, SitePolicyStatus.ALLOWED, reason, daily_limit)


@sites_app.command("deny")
def sites_deny(site: str, reason: str = typer.Option(..., help="거부 이유")) -> None:
    """사이트를 거부한다. 그 사이트의 후보는 가져오지 않는다."""
    from narrative_radar.schemas.enums import SitePolicyStatus

    _set(site, SitePolicyStatus.DENIED, reason)


@sites_app.command("reset")
def sites_reset(site: str, reason: str = typer.Option(..., help="차단 원인을 확인한 내용")) -> None:
    """차단(blocked)된 사이트를 검토 대기로 돌린다. 다시 가져오려면 allow를 실행한다."""
    from narrative_radar.db.models import SitePolicy
    from narrative_radar.schemas.enums import SitePolicyStatus

    ctx = _context("web")
    with ctx.sessions() as session:
        policy = session.get(SitePolicy, site)
        if policy is None or policy.status != SitePolicyStatus.BLOCKED:
            typer.echo(f"{site} is not blocked")
            raise typer.Exit(code=1)
    _set(site, SitePolicyStatus.PENDING_REVIEW, f"block reviewed: {reason}")


@sites_app.command("logs")
def sites_logs(site: str, limit: int = typer.Option(20, min=1)) -> None:
    """그 사이트에 보낸 요청 기록 (최근 것부터)."""
    import sqlalchemy as sa

    from narrative_radar.db.models import FetchLog

    ctx = _context("web")
    with ctx.sessions() as session:
        for log in session.scalars(
            sa.select(FetchLog)
            .where(FetchLog.domain == site)
            .order_by(FetchLog.at.desc(), FetchLog.log_id.desc())
            .limit(limit)
        ):
            typer.echo(
                f"{log.at:%Y-%m-%d %H:%M:%S} {log.outcome.value:<9} {log.status_code or '-':<4} "
                f"{log.url}  {log.detail or ''}"
            )

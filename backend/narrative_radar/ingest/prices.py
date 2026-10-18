"""시세 수집 실행 (DECISIONS D27). 관심사 트리에 있는 미국·한국 종목의 일봉을 받아 저장한다.

- 종목은 관심사 트리 순서(루트 → 최근 언급 → 가까운 노드)로 상한까지. 트리가 자라면 종목도 는다.
- 처음 받는 종목은 일정 기간을 거슬러 받고, 그 뒤로는 마지막 봉 며칠 전부터 다시 받아 덮어쓴다
  (수정주가·늦은 정정 반영).
- 상품 코드는 소스 설정에 기억해 다음부터 조회하지 않는다.
"""

import json
from dataclasses import dataclass, field
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.collectors.prices import (
    INTERVAL,
    DailyBar,
    Instrument,
    TossPriceSource,
    day_closes_at,
    market_of,
)
from narrative_radar.core.ids import new_id
from narrative_radar.db.models import PriceBar
from narrative_radar.ingest.health import record_health
from narrative_radar.ingest.runner import RunContext, _get_cursor, _set_cursor, profile_keys
from narrative_radar.schemas.enums import SourceHealthStatus

REFRESH_DAYS = 5
INSTRUMENTS_KEY = "instruments"


@dataclass
class PriceReport:
    instruments: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)  # 토스증권에서 찾지 못한 종목
    created: int = 0
    updated: int = 0


def tracked_keys(session: Session, ctx: RunContext, limit: int) -> list[str]:
    return [k for k in profile_keys(session, ctx.clock.now()) if market_of(k)][:limit]


def resolve_instruments(
    ctx: RunContext, source: TossPriceSource, keys: list[str], report: PriceReport
) -> list[Instrument]:
    raw = _get_cursor(ctx, INSTRUMENTS_KEY)
    cached: dict[str, dict[str, str | None]] = dict(raw) if isinstance(raw, dict) else {}
    out = []
    for key in keys:
        if key in cached:
            entry = cached[key]
            out.append(Instrument(key, entry["market"], entry["code"], entry.get("currency")))
            continue
        inst = source.resolve(key)
        if inst is None:
            report.unknown.append(key)
            continue
        cached[key] = {"market": inst.market, "code": inst.code, "currency": inst.currency}
        out.append(inst)
    with ctx.sessions.begin() as session:
        _set_cursor(session, ctx, INSTRUMENTS_KEY, cached)
    return out


def collect_prices(
    ctx: RunContext,
    source: TossPriceSource,
    run_id: str,
    instruments: list[Instrument],
    lookback_days: int,
    report: PriceReport | None = None,
    extend: bool = False,
) -> PriceReport:
    """extend: 이미 받은 종목도 lookback_days까지 과거로 넓힌다 (실험 창 확장 등, 한 번만 쓴다)."""
    report = report or PriceReport()
    window_start = ctx.clock.now()
    requests_before = source.client.stats.requests
    successes_before = source.client.stats.successes
    today = ctx.clock.now().date()
    for inst in instruments:
        with ctx.sessions() as session:
            first, last = session.execute(
                sa.select(sa.func.min(PriceBar.bar_date), sa.func.max(PriceBar.bar_date)).where(
                    PriceBar.source_adapter_id == ctx.source_adapter_id,
                    PriceBar.canonical_key == inst.canonical_key,
                    PriceBar.interval == INTERVAL,
                )
            ).one()
        earliest = today - timedelta(lookback_days)
        if last is None or (extend and first > earliest):
            since = earliest
        else:
            since = last - timedelta(days=REFRESH_DAYS)
        bars = source.daily_bars(inst, since)
        with ctx.sessions.begin() as session:
            for bar in bars:
                created = _upsert(session, ctx, run_id, bar)
                report.created += created
                report.updated += not created
        report.instruments.append(inst.canonical_key)
    with ctx.sessions.begin() as session:
        record_health(
            session,
            ctx.clock,
            ctx.source_adapter_id,
            window_start,
            ctx.clock.now(),
            SourceHealthStatus.OK,
            requests=source.client.stats.requests - requests_before,
            successes=source.client.stats.successes - successes_before,
            documents_listed=report.created + report.updated,
            documents_fetched=report.created,
            note=json.dumps({"instruments": report.instruments, "unknown": report.unknown}),
        )
    return report


def _upsert(session: Session, ctx: RunContext, run_id: str, bar: DailyBar) -> bool:
    now = ctx.clock.now()
    row = session.scalar(
        sa.select(PriceBar).where(
            PriceBar.source_adapter_id == ctx.source_adapter_id,
            PriceBar.canonical_key == bar.canonical_key,
            PriceBar.interval == INTERVAL,
            PriceBar.bar_date == bar.bar_date,
        )
    )
    values = {
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "currency": bar.currency,
    }
    if row is None:
        session.add(
            PriceBar(
                bar_id=new_id("pbr", now),
                source_adapter_id=ctx.source_adapter_id,
                canonical_key=bar.canonical_key,
                interval=INTERVAL,
                bar_date=bar.bar_date,
                closes_at=day_closes_at(bar.market, bar.bar_date),
                fetched_at=now,
                run_id=run_id,
                **values,
            )
        )
        session.flush()
        return True
    for k, v in values.items():
        setattr(row, k, v)
    row.fetched_at = now
    row.run_id = run_id
    return False

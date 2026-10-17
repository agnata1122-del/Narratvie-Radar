"""시세 수집과 해외·국내 종목 엮어 보기 (DECISIONS D27).

응답·가격은 형식 확인용으로 직접 작성한 예시다 (DECISIONS D0 예외).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import sqlalchemy as sa
from fastapi.testclient import TestClient
from graphkit import HBM, NV, SKH

from narrative_radar.api.app import create_app
from narrative_radar.collectors.gate import set_status
from narrative_radar.collectors.http import PoliteClient
from narrative_radar.collectors.prices import TossPriceSource
from narrative_radar.collectors.rate_limit import MinIntervalLimiter
from narrative_radar.core.config import Settings
from narrative_radar.db.models import PriceBar, SourceAdapter
from narrative_radar.ingest.prices import (
    PriceReport,
    collect_prices,
    resolve_instruments,
    tracked_keys,
)
from narrative_radar.ingest.runner import RunContext
from narrative_radar.schemas.enums import RunKind, SourceAccessStatus

SALT = "s" * 32
US_CODE = "US00000000001"  # 예시 상품 코드


def candles(days, start):
    return [
        {"dt": d, "open": v, "high": v, "low": v, "close": v, "volume": 10}
        for v, d in zip(range(start, start + len(days)), days, strict=True)
    ]


def fake_toss(us_close=50, kr_close=100):
    def handler(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/api/v2/stock-infos/code-or-symbol/NVDA":
            return httpx.Response(200, json={"result": {"code": US_CODE}})
        days = ["2026-10-16", "2026-10-15", "2026-10-14"]  # 최신부터
        if path == f"/api/v1/c-chart/us-s/{US_CODE}/day:1":
            return httpx.Response(200, json={"result": {"candles": candles(days, us_close)}})
        if path == "/api/v1/c-chart/kr-s/A000660/day:1":
            return httpx.Response(200, json={"result": {"candles": candles(days, kr_close)}})
        return httpx.Response(404)

    return handler


def test_tree_tickers_across_markets_are_collected_and_served_without_future_bars(
    g, clock, session_factory, db_url
):
    g.confirm(HBM, NV)
    g.confirm(SKH, HBM, words=("third wording sample", "fourth wording different entirely"))
    g.build()
    g.session.commit()
    clock.advance(timedelta(days=2))  # 트리는 10-16 03:00(UTC)부터 있고, 지금은 10-18
    with session_factory.begin() as s:
        set_status(s, "toss_prices", SourceAccessStatus.LIVE, "test", clock, live_enabled=True)
    ctx = RunContext(
        Settings(live_collection_enabled=True, author_hash_salt=SALT),
        session_factory,
        clock,
        "toss_prices",
    )

    def run(handler):
        client = PoliteClient(
            "NarrativeRadar/test",
            limiter=MinIntervalLimiter(0),
            guard=ctx.guard(),
            transport=httpx.MockTransport(handler),
        )
        source = TossPriceSource(client, clock)
        report = PriceReport()
        with session_factory() as s:
            keys = tracked_keys(s, ctx, 20)
        with ctx.run(RunKind.COLLECT, {}) as run_id:
            instruments = resolve_instruments(ctx, source, keys, report)
            return collect_prices(ctx, source, run_id, instruments, 30, report)

    first = run(fake_toss())
    # 트리 순서: 루트(엔비디아, 미국) → SK하이닉스(한국). HBM은 종목이 아니다
    assert first.instruments == ["US:NVDA", "KR:000660"]
    assert (first.created, first.updated) == (6, 0)
    with session_factory() as s:
        cached = s.get(SourceAdapter, "toss_prices").config["instruments"]
        assert cached["US:NVDA"] == {"market": "US", "code": US_CODE}

    # 다시 받으면 겹치는 날은 덮어쓴다 (수정주가)
    second = run(fake_toss(us_close=60))
    assert (second.created, second.updated) == (0, 6)
    with session_factory() as s:
        closes = s.scalars(
            sa.select(PriceBar.close)
            .where(PriceBar.canonical_key == "US:NVDA")
            .order_by(PriceBar.bar_date)
        ).all()
        assert closes == [62.0, 61.0, 60.0]

    client = TestClient(
        create_app(Settings(db_path=Path(db_url.removeprefix("sqlite:///"))), clock)
    )
    start = (clock.now() - timedelta(days=5)).isoformat()
    body = client.get("/api/prices", params={"start": start, "end": clock.now().isoformat()}).json()
    by_key = {x["key"]: x for x in body["series"]}
    assert [x["key"] for x in body["series"]] == ["US:NVDA", "KR:000660"]  # 깊이 순서
    assert by_key["KR:000660"]["market"] == "KR" and by_key["US:NVDA"]["market"] == "US"
    last = by_key["US:NVDA"]["bars"][-1]
    assert last[:2] == ["2026-10-16", 60.0]
    assert datetime.fromisoformat(last[2]) == datetime(2026, 10, 17, 4, 0, tzinfo=UTC)

    # 재생: 뉴욕의 10-16 거래일은 UTC 10-17 04:00에 끝난다. 그 전에는 안 보인다
    before = "2026-10-17T03:59:00+00:00"
    early = client.get("/api/prices", params={"start": start, "end": before}).json()
    early_us = next(x for x in early["series"] if x["key"] == "US:NVDA")
    assert early_us["bars"][-1][0] == "2026-10-15"
    early_kr = next(x for x in early["series"] if x["key"] == "KR:000660")
    assert early_kr["bars"][-1][0] == "2026-10-16"  # 서울의 10-16은 UTC 10-16 15:00에 끝났다


def test_prices_are_refused_until_the_source_is_enabled(g, clock, session_factory):
    g.session.commit()
    ctx = RunContext(
        Settings(live_collection_enabled=True, author_hash_salt=SALT),
        session_factory,
        clock,
        "toss_prices",
    )
    try:
        ctx.require_allowed()
    except Exception as e:  # noqa: BLE001
        assert "toss_prices" in str(e)
    else:
        raise AssertionError("price collection must be off by default")

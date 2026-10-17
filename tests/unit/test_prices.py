"""시세 소스의 형식 처리 (DECISIONS D27).

응답 구조는 2026-10-17 실제 응답에서 확인한 형태를 따라 직접 작성한 형식 확인용 예시다
(SOURCE_FEASIBILITY 결과). 상품 코드·가격·환율은 예시 값이다 (DECISIONS D0 예외).

- 종목 정보와 일봉 모두 `result`로 감싸 온다.
- 일봉 `dt`는 거래소 현지 자정에 현지 UTC 오프셋이 붙은 시각이다(`...T00:00:00-04:00`, `+09:00`).
- 일봉에는 통화가 없고 `exchangeRate`(원화 환율, 한국 종목은 1)만 있다. 미국 종목 값은 달러다.
- `nextDateTime`은 다음 페이지 첫 봉의 `dt`이고 `from`으로 넘긴다.
"""

from datetime import UTC, date, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from narrative_radar.collectors.guard import CollectionBlocked
from narrative_radar.collectors.http import PoliteClient
from narrative_radar.collectors.prices import (
    Instrument,
    TossPriceSource,
    day_closes_at,
    market_of,
)
from narrative_radar.collectors.rate_limit import MinIntervalLimiter
from narrative_radar.core.clock import FixedClock

# 2026-10-16 12:00 KST, 2026-10-15 23:00 뉴욕
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
US_CODE = "US00000000001"  # 예시 상품 코드


def candle(dt, close):
    return {
        "dt": dt,
        "base": close,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1000,
        "amount": 1,
    }


def source(handler):
    client = PoliteClient(
        "NarrativeRadar/test", limiter=MinIntervalLimiter(0), transport=httpx.MockTransport(handler)
    )
    return TossPriceSource(client, FixedClock(NOW), count=3, max_pages=4)


def api(routes):
    seen = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        seen.append(request)
        key = request.url.path
        frm = parse_qs(request.url.query.decode()).get("from", [None])[0]
        make = routes.get((key, frm)) or routes.get(key)
        return make if isinstance(make, httpx.Response) else httpx.Response(404)

    handler.seen = seen
    return handler


def test_keys_map_to_markets_and_day_ends():
    assert market_of("US:NVDA") == "US" and market_of("US:BRK.B") == "US"
    assert market_of("KR:000660") == "KR"
    assert (
        market_of("KR:ABC") is None
        and market_of("TECH:hbm") is None
        and market_of("JP:7203") is None
    )
    assert day_closes_at("KR", date(2026, 10, 15)) == datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
    assert day_closes_at("US", date(2026, 10, 15)) == datetime(2026, 10, 16, 4, 0, tzinfo=UTC)


def test_resolve_korean_codes_locally_and_us_through_stock_info():
    handler = api(
        {
            "/api/v2/stock-infos/code-or-symbol/NVDA": httpx.Response(
                200,
                json={
                    "result": {"code": US_CODE, "symbol": "NVDA", "guid": "g", "currency": "USD"}
                },
            )
        }
    )
    s = source(handler)
    assert s.resolve("KR:000660") == Instrument("KR:000660", "KR", "A000660")
    assert handler.seen == []  # 한국 종목은 조회하지 않는다
    assert s.resolve("US:NVDA") == Instrument("US:NVDA", "US", US_CODE, "USD")
    assert s.resolve("US:ZZZZ") is None  # 토스증권에 없는 종목 (404)
    assert s.resolve("TECH:hbm") is None


def test_daily_bars_page_back_to_since_and_skip_the_unfinished_day():
    path = "/api/v1/c-chart/kr-s/A000660/day:1"
    handler = api(
        {
            (path, None): httpx.Response(
                200,
                json={
                    "result": {
                        "code": "A000660",
                        "nextDateTime": "2026-10-13T00:00:00+09:00",
                        "exchangeRate": 1,
                        "exchange": "krx",
                        "candles": [
                            candle("2026-10-16T00:00:00+09:00", 105),  # 오늘: 장 중이라 버린다
                            candle("2026-10-15T00:00:00+09:00", 104),
                            candle("2026-10-14T00:00:00+09:00", 103),
                        ],
                    }
                },
            ),
            (path, "2026-10-13T00:00:00+09:00"): httpx.Response(
                200,
                json={
                    "result": {
                        "code": "A000660",
                        "nextDateTime": "2026-10-07T00:00:00+09:00",
                        "exchangeRate": 1,
                        "exchange": "krx",
                        "candles": [
                            candle("2026-10-13T00:00:00+09:00", 102),
                            candle("2026-10-12T00:00:00+09:00", 101),
                            candle("2026-10-08T00:00:00+09:00", 100),
                        ],
                    }
                },
            ),
        }
    )
    bars = source(handler).daily_bars(Instrument("KR:000660", "KR", "A000660"), date(2026, 10, 12))
    assert [(b.bar_date.isoformat(), b.close) for b in bars] == [
        ("2026-10-12", 101.0),
        ("2026-10-13", 102.0),
        ("2026-10-14", 103.0),
        ("2026-10-15", 104.0),
    ]
    assert len(handler.seen) == 2  # since에 닿아 더 넘기지 않는다
    params = parse_qs(handler.seen[0].url.query.decode())
    assert params["useAdjustedRate"] == ["true"] and params["count"] == ["3"]


def test_us_bars_use_new_york_dates():
    path = f"/api/v1/c-chart/us-s/{US_CODE}/day:1"
    handler = api(
        {
            path: httpx.Response(
                200,
                json={
                    "result": {
                        "code": US_CODE,
                        "nextDateTime": "2026-10-12T00:00:00-04:00",
                        "exchangeRate": 1350.5,
                        "candles": [
                            # 뉴욕 10-15: 아직 하루가 안 끝났다
                            candle("2026-10-15T00:00:00-04:00", 52.5),
                            candle("2026-10-14T00:00:00-04:00", 51.25),
                        ],
                    }
                },
            )
        }
    )
    inst = Instrument("US:NVDA", "US", US_CODE, "USD")
    bars = source(handler).daily_bars(inst, date(2026, 10, 14))
    assert [(b.bar_date.isoformat(), b.close) for b in bars] == [("2026-10-14", 51.25)]
    assert bars[0].currency == "USD"  # 일봉에는 통화가 없어 종목 정보의 통화를 쓴다


def test_older_date_shapes_are_still_read():
    """실제 응답은 오프셋이 붙은 시각이지만, 날짜만 오거나 자정인 시간대 없는 시각도 읽는다."""
    body = {"candles": [candle("2026-10-14", 2), candle("2026-10-13T00:00:00", 1)]}
    s = source(api({"/api/v1/c-chart/kr-s/A000660/day:1": httpx.Response(200, json=body)}))
    bars = s.daily_bars(Instrument("KR:000660", "KR", "A000660"), None)
    assert [b.bar_date.isoformat() for b in bars] == ["2026-10-13", "2026-10-14"]
    assert bars[0].currency is None


@pytest.mark.parametrize(
    "bad",
    [
        {"candles": [candle("2026-10-14T09:00:00", 1)]},  # 시간대 없는 장중 시각
        {"candles": [{"dt": "2026-10-14", "open": 1, "high": 1, "low": 1}]},  # close 없음
        {"candles": [candle("2026-10-14", 1) | {"close": "abc"}]},
        {"candles": [candle("2026-10-14", 1) | {"low": -1}]},
        {"items": []},
    ],
)
def test_unexpected_shapes_stop_instead_of_guessing(bad):
    s = source(api({"/api/v1/c-chart/kr-s/A000660/day:1": httpx.Response(200, json=bad)}))
    with pytest.raises(CollectionBlocked):
        s.daily_bars(Instrument("KR:000660", "KR", "A000660"), None)
    assert s.client.guard.tripped


def test_repeated_cursor_stops():
    body = {"nextDateTime": "same", "candles": [candle("2026-10-14", 1)]}
    s = source(api({"/api/v1/c-chart/kr-s/A000660/day:1": httpx.Response(200, json=body)}))
    with pytest.raises(CollectionBlocked, match="cursor repeated"):
        s.daily_bars(Instrument("KR:000660", "KR", "A000660"), date(2026, 1, 1))

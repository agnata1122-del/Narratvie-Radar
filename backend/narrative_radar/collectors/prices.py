"""시세: 미국·한국 종목의 일봉 (DECISIONS D27).

- 토스증권 웹(tossinvest.com)이 로그인 없이 쓰는 조회 API를 쓴다. 경로는 dd3ok/tossinvest-api-skill
  (MIT)의 문서를 따른다. 공식 API가 아니므로 경로와 응답이 예고 없이 바뀔 수 있다.
- 한 곳에서 미국·한국 종목을 같은 방식으로 받으므로 해외·국내 종목을 한 트리에서 엮어 볼 수 있다.
- 금융 팩 키를 토스증권 상품 코드로 바꾼다: 한국 `KR:000660` → `A000660`, 미국 `US:NVDA` →
  종목 정보 조회로 받은 상품 코드.
- 장이 끝난 날의 봉만 돌려준다(오늘 봉은 아직 바뀌는 중). 응답 형식이 예상과 다르면 추측하지
  않고 멈춘다.
"""

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, NoReturn
from urllib.parse import quote
from zoneinfo import ZoneInfo

from narrative_radar.collectors.guard import CollectionBlocked, TripKind
from narrative_radar.collectors.http import PoliteClient
from narrative_radar.core.clock import Clock

STOCK_INFO_URL = "https://wts-info-api.tossinvest.com/api/v2/stock-infos/code-or-symbol/{symbol}"
CHART_URL = "https://wts-info-api.tossinvest.com/api/v1/c-chart/{chart}/{code}/day:1"

SOURCE_ADAPTER_ID = "toss_prices"
INTERVAL = "1d"


@dataclass(frozen=True)
class Market:
    chart: str  # 차트 경로의 시장 구분
    tz: ZoneInfo


MARKETS = {
    "US": Market("us-s", ZoneInfo("America/New_York")),
    "KR": Market("kr-s", ZoneInfo("Asia/Seoul")),
}


def market_of(canonical_key: str) -> str | None:
    market, _, ticker = canonical_key.partition(":")
    if market == "KR" and ticker.isdigit() and len(ticker) == 6:
        return "KR"
    if market == "US" and ticker and ticker.replace(".", "").replace("-", "").isalnum():
        return "US"
    return None


def day_closes_at(market: str, day: date) -> datetime:
    """그 거래일이 현지에서 끝나는 시각(UTC). 시점 재생은 이 시각이 지난 봉만 보여준다.
    시간외 거래까지 넉넉히 덮도록 장 마감이 아니라 현지 날짜가 끝나는 때로 잡는다."""
    local_end = datetime.combine(day + timedelta(days=1), time(0, 0), MARKETS[market].tz)
    return local_end.astimezone(UTC)


@dataclass(frozen=True)
class Instrument:
    canonical_key: str
    market: str  # US / KR
    code: str  # 토스증권 상품 코드
    currency: str | None = None  # 종목 정보의 통화. 일봉 응답에는 통화가 없다


@dataclass(frozen=True)
class DailyBar:
    canonical_key: str
    market: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    currency: str | None


class TossPriceSource:
    source_adapter_id = SOURCE_ADAPTER_ID

    def __init__(
        self, client: PoliteClient, clock: Clock, count: int = 100, max_pages: int = 4
    ) -> None:
        self.client = client
        self.clock = clock
        self.count = count
        self.max_pages = max_pages

    def resolve(self, canonical_key: str) -> Instrument | None:
        """상품 코드를 찾는다. 바꿀 수 없는 키이거나 토스증권에 없는 종목(404)이면 None."""
        market = market_of(canonical_key)
        if market is None:
            return None
        ticker = canonical_key.partition(":")[2]
        if market == "KR":
            return Instrument(canonical_key, market, f"A{ticker}")
        response = self.client.get(STOCK_INFO_URL.format(symbol=quote(ticker, safe="")))
        if response.status_code == 404:
            return None
        info = _unwrap(self._json(response))
        code = info.get("code")
        if not isinstance(code, str) or not code:
            self._parse_failed(f"stock info for {ticker} has no product code")
        currency = info.get("currency")
        return Instrument(
            canonical_key, market, code, currency if isinstance(currency, str) else None
        )

    def daily_bars(self, inst: Instrument, since: date | None) -> list[DailyBar]:
        """since 이후(그날 포함)의 끝난 일봉. 최신부터 받아 since에 닿거나 페이지 상한에서
        멈춘다."""
        market = MARKETS[inst.market]
        today = self.clock.now().astimezone(market.tz).date()
        bars: dict[date, DailyBar] = {}
        cursor: str | None = None
        for _ in range(self.max_pages):
            params = {
                "count": str(self.count),
                "session": "all",
                "investMode": "krx",
                "useAdjustedRate": "true",
            }
            if cursor is not None:
                params["from"] = cursor
            url = CHART_URL.format(chart=market.chart, code=quote(inst.code, safe=""))
            body = _unwrap(self._json(self.client.get(url, params=params)))
            candles = body.get("candles")
            if not isinstance(candles, list):
                self._parse_failed("chart response has no candles list")
            # 미국 종목 일봉은 달러 값이고, 응답에는 통화 대신 원화 환율(`exchangeRate`)만 있다.
            currency = body.get("currency")
            if not isinstance(currency, str):
                currency = inst.currency
            for candle in candles:
                bar = self._bar(candle, inst, currency)
                bars[bar.bar_date] = bar
            oldest = min((b.bar_date for b in bars.values()), default=None)
            next_cursor = body.get("nextDateTime")
            if not candles or next_cursor is None or (since and oldest and oldest <= since):
                break
            if str(next_cursor) == cursor:
                self._parse_failed("chart cursor repeated")
            cursor = str(next_cursor)
        return sorted(
            (
                b
                for b in bars.values()
                if b.bar_date < today and (since is None or b.bar_date >= since)
            ),
            key=lambda b: b.bar_date,
        )

    # --- 내부 ---------------------------------------------------------------------------

    def _bar(self, candle: Any, inst: Instrument, currency: str | None) -> DailyBar:
        try:
            prices = [_number(candle[k]) for k in ("open", "high", "low", "close")]
            volume = candle.get("volume")
            return DailyBar(
                canonical_key=inst.canonical_key,
                market=inst.market,
                bar_date=_trading_date(candle["dt"], MARKETS[inst.market].tz),
                open=prices[0],
                high=prices[1],
                low=prices[2],
                close=prices[3],
                volume=None if volume is None else _number(volume),
                currency=currency,
            )
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            self._parse_failed(f"unexpected candle shape: {e!r}")

    def _json(self, response: Any) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as e:
            self._parse_failed(f"non-JSON response from {response.request.url}: {e}")
        if not isinstance(body, dict):
            self._parse_failed(f"expected JSON object, got {type(body).__name__}")
        return body

    def _parse_failed(self, reason: str) -> NoReturn:
        self.client.guard.trip(TripKind.ERROR, f"parse failed: {reason}")
        raise CollectionBlocked(reason)


def _unwrap(body: dict[str, Any]) -> dict[str, Any]:
    """토스증권 API는 결과를 `result`로 감싸는 경우가 있다. 감싸지 않은 응답도 받는다."""
    inner = body.get("result")
    return inner if isinstance(inner, dict) else body


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("price is bool")
    number = float(value)  # 숫자 문자열도 받는다. 그 밖의 값은 ValueError
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"invalid price {value!r}")
    return number


def _trading_date(value: Any, tz: ZoneInfo) -> date:
    """`dt`를 거래소 현지 날짜로. 날짜 문자열, 시간대가 있는 시각, 자정인 시간대 없는 시각만
    받는다."""
    if not isinstance(value, str):
        raise TypeError(f"dt is {type(value).__name__}")
    if len(value) == 10:
        return date.fromisoformat(value)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        return parsed.astimezone(tz).date()
    if parsed.time() == time(0, 0):
        return parsed.date()
    raise ValueError(f"dt has a time but no timezone: {value!r}")

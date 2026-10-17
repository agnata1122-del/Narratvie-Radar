# 수집 가능성 확인 (M2)

Bluesky와 Hacker News를 실제로 1–2시간 돌려 보고, 상시 수집을 시작해도 되는지 판단한다. 아래 "결과"는 실행한 뒤 채운다.

## 준비

1. **네트워크**: 실행하는 환경에서 다음 도메인에 접속할 수 있어야 한다.
   - `hn.algolia.com`, `hacker-news.firebaseio.com` (HN)
   - `jetstream2.us-east.bsky.network`, `public.api.bsky.app` (Bluesky)
2. **설정** (`.env`)
   ```bash
   NR_LIVE_COLLECTION_ENABLED=true
   NR_AUTHOR_HASH_SALT=<python -c "import secrets; print(secrets.token_hex(32))" 결과>
   ```
   salt는 한 번 정하면 바꾸지 않는다. 바꾸면 같은 작성자를 알아볼 수 없게 된다.
3. **DB와 소스**
   ```bash
   uv run nr db init
   uv run nr sources enable hackernews --accept-data-policy
   uv run nr sources enable bluesky_jetstream --accept-data-policy
   uv run nr sources list
   ```

## 실행

```bash
# HN: 2분 간격으로 1시간
uv run nr collect hackernews --loop --interval 120 --max-cycles 30

# Bluesky: 1시간 동안 스트림 수신 (다른 터미널에서)
uv run nr collect bluesky --max-minutes 60

# Bluesky 지표 재방문 (다른 터미널에서, 2분 간격)
uv run nr collect bluesky-metrics --loop

# 요약
uv run nr sources report --hours 2
```

문제가 생기면 수집기는 바로 멈추고 `nr sources list`에 `blocked` 또는 `stopped`와 이유가 나온다. 원인을 확인한 뒤 `nr sources reset <소스> --reason "..."` → `nr sources enable <소스> --accept-data-policy`로 다시 켠다.

## 확인할 것

| 항목 | 보는 곳 | 판단 기준 |
|---|---|---|
| robots.txt | 첫 요청에서 `RobotsDisallowed`가 나는지 | 금지되면 그 경로는 쓰지 않는다 |
| NVDA 관련 글 수 | report `per_hour` | 하루 수십 건 미만이면 검색어를 넓히거나 다른 소스 비중을 높인다 |
| 수집 지연 | report `median_delay_seconds` | 실시간 소스(Bluesky)는 수 초, HN은 폴링 간격 안쪽이어야 한다 |
| 스트림 대역폭 | report `stream_bytes` ÷ 수신 시간 | 하루 사용량을 추정해 상시 수집 호스트의 회선·요금과 비교한다. 너무 크면 Jetstream 압축 옵션을 검토한다 |
| 이상한 레코드 비율 | Bluesky health note의 `malformed_records` | 높으면 파싱 규칙을 고친다 |
| 삭제 비율 | report `deleted` | 삭제 반영이 실제로 일어나는지 확인한다 |
| 자동 중단 | report `health_by_status`, `last_problem` | 1–2시간 안에 멈추면 원인을 기록하고 규칙을 조정할지 논의한다 |
| GDELT 응답 | `nr discover gdelt` 결과, health note | `seendate` 형식, 결과 없음(`{}`), 검색어 오류 응답(텍스트)이 `tests/integration/test_discovery.py`의 예시와 같은지. 429가 나면 간격(`NR_GDELT_MIN_INTERVAL_SECONDS`)을 늘린다 |
| 토스증권 시세 | `nr collect prices` 결과, health note | `code-or-symbol/NVDA`가 상품 코드를 주는지, 일봉 `dt` 형식·시간대, 미국 종목 일봉 통화, `from=nextDateTime` 넘김이 `tests/unit/test_prices.py`의 예시와 같은지 |
| 응답 형식 | 실제 응답과 `tests/unit/test_hackernews.py`, `test_bluesky.py`의 예시 비교 | 다르면 수집기와 테스트 예시를 실제 형식에 맞춘다 |

## 결과

### 첫 접속 확인 (spike, 2026-10-17 07:19–07:27 UTC, 클라우드 세션)

소유자 결정으로 `toss_prices`, `gdelt`, `hackernews`, `bluesky_jetstream`을 켜고 한 번씩 돌렸다(D15·D25·D27). `web`, `dcinside_stockus`, `naver_world_nvda`는 켜지 않았고, 토스증권 커뮤니티는 보류 중이라 요청하지 않았다. 1–2시간 연속 실행은 아직 하지 않았다.

- 환경: `NR_LIVE_COLLECTION_ENABLED=true`, salt 설정됨. 여섯 호스트 모두 접속됨(`/robots.txt` 응답: firebaseio·public.api.bsky.app 200, 나머지 404 = 제한 없음). `RobotsDisallowed`는 없었다.

| 소스 | 실행 일시 (UTC) | 시간 | 글 수 | 지연 | 대역폭 | 중단 | 메모 |
|---|---|---|---|---|---|---|---|
| Hacker News | 2026-10-17 07:21:52 | 7초 (1주기, 4시간 거슬러) | 7 (live 1, backfill 6), 스냅숏 1 | 중앙값 469초 (대부분 lookback으로 늦게 본 글) | — | 없음 | 응답 형식 그대로 파싱됨. 삭제 0 |
| Bluesky | 2026-10-17 07:22:00 | 5분 | 5 (이벤트 9,245건, 게시물 8,371건 중) | 중앙값 0.04초 | 7.46MB / 300초 ≈ 25KB/s (하루 약 2.1GB 추정) | 없음 | malformed 0, 재연결 0, 삭제 이벤트 646, 계정 삭제·정지 60. 지표 재방문은 대상 없음(0건) |
| GDELT (발견) | 2026-10-17 07:21:35 | 첫 요청에서 멈춤 | 0 | — | — | **`stopped`** | robots.txt(404)는 받았고, 첫 DOC API 요청(`NVIDIA OR NVDA OR "NVIDIA Corporation"`)에서 서버가 응답 없이 연결을 끊었다(`RemoteProtocolError: Server disconnected without sending a response`). 에이전트 프록시에는 중계 실패 기록이 없었다. 규칙대로 다시 켜지 않았다. `seendate`·결과 없음·검색어 오류 응답 형식은 확인하지 못했다 |
| 토스증권 시세 | 2026-10-17 07:19:38 | 7초 | 일봉 126개 (`US:NVDA`, 2026-04-20–2026-10-16) | — | — | 없음 | 요청 2회(robots.txt 포함), 아래 형식 메모 |

### 토스증권 시세 형식 (D27 확인 항목)

실제 값은 적지 않는다. 구조만 기록한다.

- **상품 코드**: `code-or-symbol/NVDA`는 `result`로 감싼 종목 정보를 준다. `code`는 `US` + 숫자 11자리(예: `US00000000001` 꼴)이고 `symbol`, `currency`(`"USD"`), `market`(`{code, displayName}`) 등이 함께 온다.
- **응답 감싸기**: 종목 정보와 일봉 모두 `{"result": {...}}`.
- **일봉 `dt`**: 거래소 현지 자정에 현지 UTC 오프셋이 붙은 ISO 시각. 미국 `2026-10-16T00:00:00-04:00`, 한국 `2026-10-16T00:00:00+09:00` 꼴. 기존 파서가 그대로 현지 날짜로 읽는다.
- **통화**: 일봉 응답에는 `currency`가 없고 `code`, `nextDateTime`, `exchangeRate`, `candles`(한국은 `exchange: "krx"`도)만 있다. 미국 종목 봉 값은 **달러**이고 `exchangeRate`는 원화 환율이다(한국 종목은 1). 원화 환산값이 아니므로 변화율 비교에 환율이 섞이지 않는다.
- **봉 필드**: `dt`, `base`, `open`, `high`, `low`, `close`(실수), `volume`, `amount`(정수).
- **페이지 넘김**: `nextDateTime`은 다음 페이지 첫 봉의 `dt`다. `from=<nextDateTime>`으로 넘기면 겹치지 않고 이어진다(휴장일은 빠진다). 미국·한국 모두 확인.
- **한국 종목 경로**: `KR:000660` → `A000660`, `kr-s` 차트를 `TossPriceSource.daily_bars`로 한 번 읽었다(저장하지 않음). 형식 문제 없음.
- **코드 수정**: 일봉에 통화가 없어 `currency`가 비던 것을, 종목 정보의 `currency`를 `Instrument`에 담아 쓰게 고쳤다(한국 종목은 종목 정보를 조회하지 않으므로 비어 있고, 화면은 한국 종목을 원화로 표시한다). `tests/unit/test_prices.py` 예시를 실제 구조로 맞췄다.

### 남은 일

- GDELT: 원인(서버 쪽 연결 끊김 — 요청 간격·검색어 길이·일시 장애 중 무엇인지)을 소유자가 확인한 뒤 `nr sources reset gdelt --reason ...` → `enable`로 다시 시도한다. 그때 `seendate`·빈 결과·검색어 오류 형식을 확인한다.
- HN·Bluesky 1–2시간 연속 실행, Jetstream이 몇 시간 전까지 다시 보내 주는지(커서 재생 범위).
- Bluesky 대역폭이 하루 약 2GB로 추정된다. 상시 수집 전에 Jetstream 압축 옵션을 검토한다.

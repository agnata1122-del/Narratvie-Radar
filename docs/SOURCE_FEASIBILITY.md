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
| 응답 형식 | 실제 응답과 `tests/unit/test_hackernews.py`, `test_bluesky.py`의 예시 비교 | 다르면 수집기와 테스트 예시를 실제 형식에 맞춘다 |

## 결과

아직 실행하지 않았다. (이 개발 환경은 위 도메인이 네트워크 정책으로 막혀 있다.)

| 소스 | 실행 일시 | 시간 | 글 수 | 지연 | 대역폭 | 중단 | 메모 |
|---|---|---|---|---|---|---|---|
| Hacker News | | | | | — | | |
| Bluesky | | | | | | | |

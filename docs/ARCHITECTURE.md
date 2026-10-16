# 아키텍처

PRD 4장의 계층 구조를 따른다. 이 문서는 실제 코드 위치와 데이터 흐름을 설명한다.

## 데이터 흐름

```text
수집기 (collectors/)
  │  목록 폴링, 본문·댓글 읽기, 지표 스냅샷 재방문
  ▼
표준화·중복 제거
  │  Document 스키마, content_hash, derivation group
  ▼
프리필터 → 분류 (classifiers/)
  │  세션 분류(지침 v1, JSON) → 스키마 검증 → classification_runs (추가만)
  ▼
변경안(ChangeSet) 검증 (graph/, normalization/, discovery/)
  │  개체 정규화, depth, 확장 예산, 근거 요건
  ▼
반영
  │  nodes · edges · claims · edge_evidence · narratives
  │  graph_events (원인 · run_id · available_at)
  ▼
틱마다
  │  위키 섹션 갱신 (wiki_revisions), 내러티브 상태, 지표 버킷
  ▼
조회 API (api/) ── as_of 기준 ──▶ 웹앱 (apps/web)
```

## 원칙

- **AI는 변경안만 만든다.** LLM 출력은 검증을 통과해야 DB에 반영된다(PRD 4.1).
- **시간은 주입한다.** `core/clock.py`의 `Clock`으로만 현재 시각을 얻는다.
- **과거는 고치지 않는다.** 이력 테이블은 추가만 한다. 과거 시점 상태는 `available_at <= t`인 기록만으로 복원한다.
- **수집과 분석을 분리한다.** 수집기는 원문과 지표만 저장하고, 분석은 별도 실행(`pipeline_runs`)으로 한다. 분석 로직이 바뀌면 원문에서 다시 계산할 수 있다.

## 코드 위치

| 경로 | 역할 |
|---|---|
| `backend/narrative_radar/core/` | 설정, 시계, ID, 소스 등록부 |
| `backend/narrative_radar/schemas/` | Pydantic 스키마 (API·LLM 입출력, JSON Schema export) |
| `backend/narrative_radar/db/` | SQLAlchemy 모델, 세션, 마이그레이션 |
| `backend/narrative_radar/collectors/` | 소스별 어댑터. `http.py`(유일한 HTTP 클라이언트: 최소 간격, robots.txt, 정직한 UA, GET만), `guard.py`(첫 문제에서 즉시 중단), `author.py`(작성자 HMAC), `gate.py`(수집 허용 조건과 상태 변경), `hackernews.py`, `bluesky.py` |
| `backend/narrative_radar/ingest/` | 수집 결과 저장(`store.py`: 중복 방지, 스냅샷, 삭제 반영), 수집 실행기(`runner.py`), 수집 상태 기록, 현황 요약 |
| `backend/narrative_radar/classifiers/` | 세션 분류 내보내기·검증(`session.py`), 분류 지침(`guidelines/`), 온톨로지 문맥, 규칙 기반 기준 분류기 |
| `backend/narrative_radar/graph/` | 그래프 반영: 개체 정규화(`resolve.py`), 변경안(`changeset.py`), 반영과 관계 확정(`builder.py`), 복사 판정 지문(`fingerprint.py`) |
| `backend/narrative_radar/discovery/` | 관심사 그래프 자동 확장: 탐색 깊이, 하루 예산, 검토 대기 |
| `backend/narrative_radar/api/` | FastAPI 앱 |
| `backend/narrative_radar/cli.py` | `nr` 명령줄 도구 |
| `apps/web/` | React 웹앱 |
| `schemas/` | 내보낸 JSON Schema |
| `tests/` | 단위·통합 테스트 |
| `data/` | 로컬 DB와 원문 (커밋하지 않음) |

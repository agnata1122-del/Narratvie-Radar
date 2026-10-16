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
  │  Haiku 구조화 출력 → classification_runs (추가만)
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
| `backend/narrative_radar/collectors/` | 소스별 어댑터, 레이트 리밋, 자동 중단 |
| `backend/narrative_radar/api/` | FastAPI 앱 |
| `backend/narrative_radar/cli.py` | `nr` 명령줄 도구 |
| `apps/web/` | React 웹앱 |
| `schemas/` | 내보낸 JSON Schema |
| `tests/` | 단위·통합 테스트 |
| `data/` | 로컬 DB와 원문 (커밋하지 않음) |

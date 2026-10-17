# 데이터 스키마

정의는 `backend/narrative_radar/db/models.py`(DB)와 `backend/narrative_radar/schemas/`(API·LLM 입출력)에 있다. API·LLM 입출력의 JSON Schema는 `schemas/`에 내보내 두며, 테스트가 최신 상태인지 확인한다(`uv run nr schemas export`).

## 시간 필드 (PRD 10.3)

| 필드 | 의미 |
|---|---|
| `published_at` | 출처에 표시된 작성 시각. 출처 서버 시계 기준 |
| `observed_at` | 수집기가 처음 본 시각 |
| `processed_at` | 분석을 마친 시각 |
| `available_at` | 시스템이 이 정보를 쓸 수 있게 된 시각. **과거 상태 복원과 섀도 테스트의 기준** |
| `event_time` | 현실에서 그 일이 일어난 시각(알 수 있는 경우) |
| `recorded_at` | 이벤트 행을 기록한 시각 |

- 모든 시각은 시간대가 있는 UTC로 저장한다. 시간대가 없는 값은 저장할 때 오류가 난다.
- 저장 형식은 고정 길이 문자열(`2026-10-16T03:00:00.000000Z`)이라 문자열 비교가 시간 비교와 같다.

## 테이블

### 설정

| 테이블 | 역할 |
|---|---|
| `interest_profiles` | 관심사와 자동 탐색 설정 (root, depth, 일일 신규 노드 예산, 최소 독립 근거 수, 도메인 팩 `domain`) |
| `source_adapters` | 소스별 상태(`not_authorized / test_mode / live / paused / blocked / stopped`)와 `live_enabled` |
| `pipeline_runs` | 수집·분석 실행 단위. mode(`live / retrospective`), model·prompt·schema·code 버전 |

### 원천 데이터

| 테이블 | 역할 |
|---|---|
| `documents` | 게시글 메타데이터. `(source_adapter_id, external_id)`가 유일하다. 작성자는 `author_hash`만 |
| `raw_documents` | 본문. 로컬 DB에만 있고 외부로 그대로 내보내지 않는다 |
| `document_comments` | 댓글 |
| `document_metric_snapshots` | 관측 시각별 댓글·조회·추천 수. 문서 행에는 이 값을 두지 않는다 |
| `derivation_groups` | 복사·전재된 글 묶음. 독립 근거를 셀 때 쓴다 |
| `source_health` | 수집 상태 시계열. 관측 공백을 표시하는 데 쓴다 |

### 분류·지식 그래프

| 테이블 | 역할 |
|---|---|
| `classification_runs` | LLM 출력 원본. 반영 전 변경안 |
| `nodes` | 지식 객체. `canonical_key`가 유일하다 (예: `US:NVDA`) |
| `node_aliases` | 같은 개체의 다른 표기. `alias_normalized`로 찾는다 |
| `claims` | 문서에서 추출한 주장. `evidence_status`(원문에서 어떤 성격으로 제시됐나)와 `verification_status`(내용이 확인됐나)를 따로 둔다 |
| `narratives` | 같은 명제를 말하는 주장 묶음. 그래프에서는 `narrative` 노드로 나타난다 |
| `narrative_claims` | 주장의 내러티브 배정 이력 |
| `edges` | 노드 간 관계. `(source, target, relation_type)`가 유일하고 자기 자신을 가리킬 수 없다 |
| `edge_evidence` | 관계의 근거. 문서 하나는 관계 하나에 근거를 한 번만 더한다 |
| `graph_events` | 그래프 변화 이력. `cause`로 새 관측·백필·재분류를 구분한다 |
| `wiki_revisions` | 위키 버전 |
| `node_metric_buckets` | 노드 언급 지표. 다시 계산하면 새 행을 추가한다 |

### 개인화

| 테이블 | 역할 |
|---|---|
| `profile_nodes` | 관심사별 자동 확장 결정 이력 (포함 / 검토 대기 / 제외, depth) |
| `viewers` | 익명 방문자. `previous_seen_at`은 "지난 방문 이후"의 기준 시각 (30분 안에 다시 열면 바뀌지 않음) |
| `viewer_overlays` | 방문자별 승인·거절·숨김. 공통 그래프는 바꾸지 않는다 |
| `saved_views` | 저장된 필터 |
| `classification_feedback` | 테스터 피드백과 그때의 모델·프롬프트·스키마 버전 |

## 추가만 허용하는 테이블

`classification_runs`, `document_metric_snapshots`, `edge_evidence`, `graph_events`, `narrative_claims`, `node_metric_buckets`, `profile_nodes`, `wiki_revisions`는 DB 트리거로 UPDATE와 DELETE가 막혀 있다. 고쳐야 하면 새 행을 추가한다.

이력 테이블에서 시점 t의 값은 "같은 대상에 대해 `available_at <= t`인 마지막 행"이다.

`nodes`, `edges`, `narratives`, `documents`의 상태 컬럼은 현재 상태 캐시이고, 과거 상태는 이력에서 복원한다.

## 마이그레이션

```bash
uv run nr db init        # 마이그레이션 적용 + 기본 데이터 (여러 번 실행해도 안전)
uv run alembic revision --autogenerate -m "..."   # 모델을 바꾼 뒤
```

SQLite라서 Alembic은 batch 모드로 동작한다. 테스트(`tests/integration/test_db_schema.py`)가 마이그레이션 결과와 모델이 일치하는지 확인한다.

## 노드 유형과 키 (DECISIONS D22)

노드 유형은 분야와 무관하다: `organization`(조직), `person`(공인), `product`(제품·작품), `technology`, `topic`(주제·산업·이슈), `event`, `place`, `narrative`.
키는 공통 형식 `ORG:` `PERSON:` `PRODUCT:` `TECH:` `TOPIC:` `EVENT:` `PLACE:` `NARRATIVE:` + 소문자 슬러그이고, 도메인 팩이 형식을 더할 수 있다(금융 팩: 상장사 `US:NVDA`, 산업 `INDUSTRY:슬러그`).
주장의 태도(`stance`)는 `positive/negative/neutral/mixed`, 방향(`polarity`)은 `enabler/constraint/neutral`이다.
마이그레이션 0008 이전 값(company, industry, bullish, bearish, growth_driver)은 DB에서 바꿨고, 추가 전용 테이블에 남은 분류 결과는 읽을 때 바꾼다.


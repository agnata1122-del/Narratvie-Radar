# Narrative Radar

> 이 문서는 프로젝트 소유자가 작성한 PRD v0.2 원문이다. 원문은 고치지 않고, 구현 중 바뀐 결정과 그 이유는 [DECISIONS.md](DECISIONS.md)에 기록한다.

**Personal Intelligence Graph**

**Product Requirements Document — MVP v0.2**

- 프로젝트 유형: AI 기반 개인화 인텔리전스 웹앱
- 개발 방식: Claude Code 중심 AI-assisted Development
- 개발 목표: 실제로 작동하고 외부 테스터가 체험할 수 있는 웹앱 MVP
- 초기 도메인: 미국 주식
- 초기 관심사: NVIDIA (NVDA)
- 탐색 깊이: 2-Hop
- 자동 확장: Enabled

---

## 1. 프로젝트 개요

### 1.1 제품 정의

Narrative Radar는 사용자가 관심사를 설정하면 AI가 관련 데이터를 탐색하고, 파편화된 정보를 구조화하여 자동으로 지식 그래프를 생성하는 개인화 인텔리전스 플랫폼이다.

수집된 데이터는 AI에 의해 분류·해석되며, 개체와 이슈 간 관계를 바탕으로 Living Wiki와 Temporal Knowledge Graph를 구축한다.

사용자는 Windy와 유사한 시간 재생 인터페이스를 통해 이슈가 생성·성장·연결·분화·소멸하는 과정을 시각적으로 탐색할 수 있다.

제품의 핵심 가치는 단순 정보 검색이나 요약이 아니라 다음에 있다.

파편화된 데이터에서 의미 있는 관계를 발견하고, 그 관계의 시간적 변화를 관측하여 사용자가 새로운 통찰을 얻도록 지원한다.

### 1.2 핵심 철학

Narrative Radar는 AI가 미래를 예측하는 시스템이 아니다.

현재 발생하고 있지만 사용자가 인지하지 못한 의미 있는 변화와 관계를 발견하는 시스템이다.

핵심 기능은 다음과 같다.

1. Data Acquisition
2. AI Classification
3. Knowledge Discovery
4. Living Wiki Generation
5. Temporal Knowledge Graph
6. Personalized Intelligence
7. Explainable Early Warning
8. Strategy Validation

### 1.3 첫 번째 실증 환경

최초 실증 분야는 미국 주식 커뮤니티다.

주요 데이터 소스는 다음과 같다.

* 디시인사이드 미국주식갤러리
* 네이버 종목토론실
* 미국 주식 시세 API
* 기업 공식 공시 및 뉴스 데이터(보조)

단, 외부 사이트의 자동 수집은 해당 사이트의 이용 조건과 필요한 권한을 확인한 경우에만 활성화한다.

첫 개발 단계에서는 데이터 소스별 어댑터를 구현하고, 허가된 데이터 또는 테스트 데이터로 전체 파이프라인을 검증할 수 있어야 한다.

---

## 2. 제품 비전

### 2.1 단기 목표

NVIDIA를 관심사로 설정하면 AI가 관련 이슈를 추출하고 2-Hop 이내의 지식 그래프를 자동으로 생성하는 웹앱을 구축한다.

사용자는 다음을 수행할 수 있어야 한다.

* 관심사 등록
* 데이터 소스 선택
* 자동 탐색
* 노드 생성
* 관계 시각화
* 위키 탐색
* 시간별 변화 관찰
* 사용자 정의 필터 설정

### 2.2 중기 목표

관심사별 이상징후 탐지 및 알림 기능을 추가한다.

금융 데이터에서는 시장 가격과 커뮤니티 신호를 결합해 가상 매매 전략을 검증한다.

### 2.3 장기 목표

금융에 종속되지 않는 범용 Personal Intelligence Graph 플랫폼으로 확장한다.

적용 가능한 분야는 다음과 같다.

* 금융 및 투자
* 기업 HR 및 조직문화
* Corporate Affairs
* 소비자 리뷰 및 브랜드
* 게임 커뮤니티
* 산업 및 기술 동향
* 개발자 커뮤니티
* 학술 및 연구

각 도메인은 공통 인텔리전스 엔진을 공유하되, 데이터 소스와 도메인별 분류 체계는 별도로 설정한다.

---

## 3. MVP 범위

### 3.1 초기 설정

```yaml
project:
  name: Narrative Radar
  version: 0.2
  mode: webapp
interest:
  root: NVIDIA
  ticker: NVDA
  depth: 2
  auto_expand: true
sources:
  dcinside_stockus:
    enabled: true
    mode: authorized_adapter
  naver_stock_discussion:
    enabled: true
    mode: authorized_adapter
ai:
  primary_model: claude_haiku
  structured_output: true
  auto_wiki: true
graph:
  temporal: true
  evidence_required: true
  replay_enabled: true
trading:
  shadow_trading: planned
  live_trading: false
```

enabled는 데이터 소스의 어댑터가 프로젝트에 포함된다는 의미다. 실제 라이브 수집 여부는 해당 소스의 접근 권한 및 연동 가능 상태에 따라 별도로 제어한다.

### 3.2 MVP 필수 기능

#### P0 — 반드시 구현

1. 관심사 설정 화면
2. 데이터 소스 어댑터
3. 데이터 표준화
4. AI 기반 게시글 분류
5. 기존 개체 및 이슈 식별
6. 신규 노드 생성
7. 노드 관계 추출
8. Living Wiki 자동 생성
9. Temporal Graph 구축
10. 그래프 시각화
11. 시간 슬라이더
12. 노드 상세 정보 및 근거 확인
13. 사용자 필터
14. 자동 확장 깊이 제한

#### P1 — 초기 확장

1. 커뮤니티별 관심도 지표
2. 댓글 증가율
3. 신규 관계 탐지
4. 관심도 급등 알림
5. 그래프 스냅샷 비교
6. 사용자 피드백
7. 시장 가격 오버레이

#### P2 — 후속 개발

1. Shadow Trading
2. 복수 관심사 지원
3. 다중 사용자 개인화
4. 에이전트 자동 스케줄링 고도화
5. 모바일 최적화
6. PWA
7. 외부 API 제공

---

## 4. 시스템 아키텍처

```text
┌─────────────────────────────────────────┐
│             USER INTEREST               │
│                                         │
│      NVIDIA / Depth 2 / Auto ON         │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│        PERSONAL DISCOVERY AGENT         │
│                                         │
│ - 관심사 해석                           │
│ - 탐색 범위 결정                        │
│ - 수집 대상 선정                        │
│ - 자동 확장 제어                        │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│           DATA ACQUISITION              │
│                                         │
│ - DC Inside Adapter                     │
│ - Naver Discussion Adapter              │
│ - Market Data Adapter                   │
│ - Official Information Adapter          │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│           AI UNDERSTANDING              │
│                                         │
│ - Noise Filtering                       │
│ - Classification                        │
│ - Entity Extraction                     │
│ - Topic Discovery                       │
│ - Relationship Extraction               │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│           KNOWLEDGE ENGINE              │
│                                         │
│ - Entity Resolution                     │
│ - Ontology Management                   │
│ - Knowledge Graph                       │
│ - Living Wiki                           │
│ - Evidence Management                   │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│           TEMPORAL ENGINE               │
│                                         │
│ - Graph Events                          │
│ - Historical State                      │
│ - Time Replay                           │
│ - Anomaly Detection                     │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│          PERSONALIZED WEB APP           │
│                                         │
│ - Narrative Radar                       │
│ - Wiki Explorer                         │
│ - Timeline Player                       │
│ - Custom Filters                        │
│ - Signals                               │
│ - Trading Lab (Future)                  │
└─────────────────────────────────────────┘
```

### 4.1 아키텍처 원칙

* 데이터 수집과 분석 엔진을 분리한다.
* AI 모델과 데이터베이스를 분리한다.
* AI는 데이터 변경안을 생성하고, 애플리케이션이 검증 후 반영한다.
* 공통 지식 그래프와 사용자별 관심사 그래프를 분리한다.
* 모든 관계는 근거와 생성 이력을 가져야 한다.
* 시계열 그래프는 과거 상태를 복원할 수 있어야 한다.
* 금융 관련 로직은 범용 Knowledge Engine에 종속시키지 않는다.

---

## 5. 데이터 수집 설계

### 5.1 데이터 소스

#### Source A — DC Inside 미국주식갤러리

주요 목적:

* 새로운 투자 이슈 발견
* 종목별 관심도 분석
* 집단심리 변화
* 투자 논리 및 논쟁 추출
* 종목과 산업의 관계 탐지

수집 대상:

* 게시글 제목
* 게시글 본문
* 게시 시각
* 댓글 수
* 댓글 내용(허용된 경우)
* 조회 수
* 게시글 식별자
* 출처 URL

#### Source B — 네이버 종목토론실

주요 목적:

* 종목별 관심도 추적
* 댓글 활성도 분석
* 게시글 증가량
* 논쟁 집중도
* 커뮤니티 간 관심 이동 비교

초기에는 텍스트의 전체 의미 분석보다 계량적 지표를 우선한다.

#### Source C — 시장 데이터

후속 연동 대상:

* 주가
* 거래량
* 변동률
* 시가총액
* 거래 시각
* 시장 이벤트

초기에는 가격 오버레이 용도로 사용하고 이후 Shadow Trading에서 활용한다.

### 5.2 공통 데이터 구조

```json
{
  "document_id": "doc_000001",
  "source": "dcinside",
  "source_type": "community",
  "external_id": "123456",
  "title": "example",
  "published_at": "2026-10-13T10:00:00+09:00",
  "observed_at": "2026-10-13T10:02:00+09:00",
  "processed_at": null,
  "comment_count": 25,
  "view_count": 300,
  "content_hash": "sha256_example",
  "content_access_status": "permitted",
  "source_url": "https://example.com/post/123456"
}
```

원문 저장은 해당 데이터에 대한 이용 권한이 허용하는 범위에서만 수행한다.

### 5.3 수집 원칙

* 출처별 어댑터 사용
* 중복 게시글 식별
* 작성 시각과 관측 시각 분리
* 사이트별 호출 빈도 제한
* 수집 실패 재시도 정책
* 소스별 상태 관리
* 데이터 이용 권한에 따른 활성화
* 작성자 식별 정보의 불필요한 저장 금지

비공식 API나 브라우저 자동화는 데이터 이용 권한을 대신하지 않는다.

---

## 6. AI Classification Engine

### 6.1 목적

수집된 비정형 텍스트를 정형 데이터로 변환한다.

#### 기본 분류 항목

* 관련성
* 종목
* 기업
* 산업
* 기술
* 사건
* 투자 관점
* 긍정·부정·중립
* 주장
* 추측
* 정보성
* 노이즈
* 기존 이슈와의 관계

### 6.2 권장 모델 구성

초기 모델은 Claude Haiku 계열을 사용한다.

이후 비용과 성능을 검증해 선택적으로 다음을 추가한다.

* JEV 계열 선택지 기반 분류 방식
* GLiNER
* BERTopic
* Sentence Transformers
* 경량 임베딩 모델

초기부터 여러 모델을 강제로 결합하지 않는다.

Haiku 단독 분석을 기준선으로 확보한 다음 다른 분류 모델을 비교한다.

### 6.3 출력 데이터

```json
{
  "document_id": "doc_000001",
  "relevance": 0.92,
  "entities": [
    {
      "name": "NVIDIA",
      "type": "company",
      "canonical_key": "US:NVDA"
    }
  ],
  "topics": [
    "AI Infrastructure",
    "HBM Supply"
  ],
  "stance": "bullish",
  "claims": [
    {
      "subject": "NVIDIA",
      "predicate": "RELATED_TO",
      "object": "HBM Supply",
      "evidence_status": "community_opinion"
    }
  ],
  "classification_status": "review"
}
```

점수는 실제 보정된 확률이 아니라 모델 출력 지표로 취급한다.

판단이 불확실하면 억지로 분류하지 않고 검토 상태로 남긴다.

---

## 7. Knowledge Discovery Engine

### 7.1 핵심 목표

게시글마다 노드를 생성하는 것이 아니다.

여러 게시글에서 공통으로 등장하는 개체·이슈·사건·주장을 식별하고 지속 가능한 지식 객체로 통합한다.

예를 들어 NVIDIA 관련 게시글 1,000개가 입력되더라도 NVIDIA 기업 노드는 하나만 존재해야 한다.

### 7.2 노드 유형

```yaml
node_types:
  - company
  - industry
  - technology
  - topic
  - event
  - claim
```

필요한 경우 도메인별로 추가할 수 있다.

### 7.3 관계 유형

```yaml
edge_types:
  - RELATED_TO
  - PART_OF
  - BELONGS_TO
  - SUPPLIES_TO
  - COMPETES_WITH
  - AFFECTS
  - CLAIMED_CAUSE_OF
  - SUPPORTS
  - CONTRADICTS
  - CO_MENTIONED_WITH
```

관계 유형은 반드시 구분한다.

특히 함께 언급되었다는 사실과 인과관계가 있다는 주장은 동일하게 취급하지 않는다.

### 7.4 노드 정규화

```text
NVIDIA
  = NVDA
  = 엔비디아
  = NVIDIA Corporation
```

동일 개체에 대한 여러 표현은 하나의 Canonical Node로 통합한다.

기존 노드 검색에는 다음 방식을 조합한다.

1. Canonical ID 매칭
2. Alias Dictionary
3. Embedding Similarity
4. LLM 검증

---

## 8. Personal Intelligence Graph

### 8.1 사용자별 관심사 설정

사용자는 하나 이상의 관심사를 등록할 수 있도록 설계한다.

MVP에서는 NVIDIA 하나만 지원한다.

```yaml
profile:
  name: NVIDIA Research
  root_interest: NVIDIA
  max_depth: 2
  auto_expand: true
discovery:
  max_new_nodes_per_day: 15
  minimum_independent_evidence: 2
  require_relevance: true
  allow_depth_overflow: false
```

### 8.2 탐색 깊이

#### Depth 0

사용자가 등록한 직접 관심사.

예시:

NVIDIA

#### Depth 1

직접 관련된 기업·산업·기술·이슈.

예시:

* AI Infrastructure
* HBM
* Data Center
* GPU Market

#### Depth 2

1차 노드와 의미 있는 관계를 가지며 루트 관심사에도 설명 가능한 연관성이 있는 개체.

예시:

* SK Hynix
* Data Center Power
* Advanced Cooling
* Export Restrictions

위 내용은 그래프 설명을 위한 예시다.

실제 관계 생성에는 근거 확인이 필요하다.

### 8.3 자동 확장 조건

새로운 노드는 다음 조건을 검토한다.

* 현재 관심사와 관련 있는가?
* 최대 탐색 깊이를 초과하지 않는가?
* 기존 노드와 중복되지 않는가?
* 관계의 근거가 있는가?
* 독립된 출처가 충분한가?
* 확장 예산을 초과하지 않는가?

불확실한 후보는 자동 확정하지 않고 사용자 검토 대상으로 표시한다.

### 8.4 사용자 개인화 구조

지식 데이터를 다음 두 계층으로 구분한다.

#### Global Knowledge Graph

공통 데이터에서 추출된 개체·주장·이슈·관계.

#### Personal Knowledge Graph

사용자 관심사에 따라 선택된 서브그래프.

개인별로 다른 요소:

* 루트 관심사
* 탐색 깊이
* 활성화된 데이터 소스
* 중요도 가중치
* 사용자 필터
* 자동 확장 조건
* 알림 조건

공통 정보는 재사용하되 개인 설정과 비공개 데이터는 사용자별로 분리한다.

---

## 9. Living Wiki Engine

### 9.1 설계 방향

Andrej Karpathy의 LLM Wiki 접근과 Obsidian의 양방향 링크 개념을 참고한다.

그러나 Obsidian 애플리케이션 자체에는 의존하지 않는다.

제품의 핵심 데이터는 자체 DB에서 관리한다.

Markdown은 읽기·내보내기용 표현 형식이다.

### 9.2 위키 자동 생성

노드별로 위키 문서를 자동 생성한다.

예시:

```markdown
# NVIDIA
## Overview
NVIDIA 관련 누적 지식 요약
## Related Topics
- [[AI Infrastructure]]
- [[HBM]]
- [[Data Center]]
## Current Narratives
현재 관찰되는 주요 논점
## Emerging Issues
최근 새롭게 등장한 관련 이슈
## Conflicting Claims
상충하는 주장과 각각의 근거
## Historical Changes
시간에 따른 이슈 변화
## Sources
원문 근거와 관측 시각
```

### 9.3 위키 갱신 방식

새로운 문서가 입력되면 다음 순서로 처리한다.

1. 관련 노드 검색
2. 기존 위키 조회
3. 새롭게 확인된 정보 비교
4. 변경 사항 생성
5. 검증
6. 위키 수정
7. 버전 저장
8. 관련 그래프 이벤트 생성

전체 문서를 매번 다시 작성하지 않는다.

변경이 필요한 영역을 중심으로 갱신한다.

### 9.4 위키 버전 관리

각 위키는 다음 정보를 가진다.

* Wiki ID
* Node ID
* Version
* Updated At
* Available At
* Source References
* Model Version
* Schema Version

이전 버전은 삭제하지 않는다.

시간 재생 시에는 해당 시점에 실제로 존재했던 위키 버전을 사용한다.

---

## 10. Temporal Knowledge Graph

### 10.1 핵심 개념

일반적인 지식 그래프가 현재 지식의 관계를 보여준다면, Temporal Knowledge Graph는 그 관계가 시간에 따라 어떻게 변화했는지 보여준다.

시스템은 최소한 다음 변화를 기록한다.

* 노드 생성
* 노드 재등장
* 노드 활성도 증가
* 노드 활성도 감소
* 신규 엣지 생성
* 관계 강도 증가
* 관계 강도 감소
* 관계 유형 변경
* 이슈 군집 형성
* 이슈 군집 분화

### 10.2 이벤트 데이터

```json
{
  "event_id": "evt_001",
  "event_type": "EDGE_CREATED",
  "source_node": "NVIDIA",
  "target_node": "HBM Supply",
  "relation_type": "RELATED_TO",
  "recorded_at": "2026-10-13T11:00:00+09:00",
  "available_at": "2026-10-13T11:01:00+09:00",
  "evidence_ids": ["doc_001", "doc_002"]
}
```

### 10.3 시간 필드

최소한 다음 필드를 구분한다.

```text
published_at
observed_at
processed_at
available_at
event_time
```

Shadow Trading과 과거 그래프 복원은 available_at을 기준으로 한다.

미래에 수집한 정보를 과거에 알고 있었다고 처리해서는 안 된다.

### 10.4 시간 재생

사용자는 시간 슬라이더를 움직여 특정 시점의 그래프를 확인한다.

필수 기능:

* Play
* Pause
* Step Forward
* Step Back
* Time Range
* Playback Speed
* Event Highlight
* Historical Wiki

과거 시점으로 이동하면 그래프와 위키가 동일한 시간 기준으로 변경되어야 한다.

---

## 11. 그래프 시각화

### 11.1 핵심 UX

제품의 중심 화면은 Temporal Knowledge Graph다.

그래프는 단순 장식이 아니라 정보 탐색의 주요 인터페이스여야 한다.

Windy처럼 시간에 따른 변화를 직관적으로 관찰할 수 있어야 한다.

### 11.2 노드 표현

| 요소 | 의미 |
|---|---|
| 크기 | 관심도 또는 선택한 중요도 지표 |
| 색상 | 노드 유형 |
| 채도 | 최근 변화 강도 |
| 테두리 | 신규·재등장·검토 상태 |
| 위치 | 의미적 군집 |

노드의 크기는 사용자가 기준을 변경할 수 있도록 한다.

예를 들어 다음 중 선택할 수 있다.

* Mention Volume
* Attention Change
* Graph Centrality
* Composite Signal

서로 다른 지표를 하나의 불명확한 점수로 혼합하지 않는다.

### 11.3 엣지 표현

| 요소 | 의미 |
|---|---|
| 두께 | 연결 강도 |
| 색상 | 관계 유형 |
| 점선 | 추론·검토 중 관계 |
| 실선 | 정의된 검증 기준을 충족한 관계 |
| 강조 효과 | 신규 생성 또는 급격한 변화 |

### 11.4 화면 안정성

그래프의 노드 위치가 시간 재생 중 과도하게 변경되면 사용자가 변화를 추적하기 어렵다.

따라서 다음 원칙을 적용한다.

* 기준 레이아웃 유지
* 노드의 상대적 위치 안정화
* 신규 노드 등장 시 제한적인 애니메이션
* 변화된 요소만 강조
* 군집별 축소·확대
* 노드가 많아지면 단계별 표시

시각화의 우선순위는 화려함보다 판독성이다.

---

## 12. 웹앱 UI/UX

### 12.1 개발 형태

Desktop-first Web Application

기본 화면은 PC 브라우저를 기준으로 설계한다.

테스터는 링크를 통해 접속할 수 있어야 한다.

후속으로 PWA를 지원한다.

### 12.2 메인 화면

```text
┌───────────────────────────────────────────────────────────┐
│ Narrative Radar                                           │
│                                                           │
│ [NVIDIA] [Depth 2] [Auto ON]      [Search] [Settings]     │
├──────────────┬─────────────────────────┬──────────────────┤
│              │                         │                  │
│ FILTERS      │   KNOWLEDGE GRAPH       │  WIKI INSPECTOR  │
│              │                         │                  │
│ Sources      │        ○──○             │ Node Summary     │
│              │       /    \            │                  │
│ Time Range   │      ○──●──○            │ Related Issues   │
│              │          \              │                  │
│ Node Types   │           ○             │ Evidence         │
│              │                         │                  │
│ Relevance    │                         │ History          │
│              │                         │                  │
├──────────────┴─────────────────────────┴──────────────────┤
│                                                           │
│  ◀   ▶   ━━━━━━━━━●━━━━━━━━━━━━━━━━━━━                 │
│                                                           │
│  Timeline / Issue Activity / Graph Events                 │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

### 12.3 화면 구성

#### Radar

메인 그래프와 시간 재생.

#### Wiki

지식 노드별 자동 위키.

#### Sources

원문 출처 및 근거 탐색.

#### Signals

이슈 변화 및 이상징후.

#### Settings

관심사, 탐색 깊이, 자동 확장 설정.

#### Trading Lab

후속 Shadow Trading 기능.

### 12.4 디자인 방향

* 미니멀한 데이터 터미널
* 낮은 시각적 피로도
* 그래프 중심
* 불필요한 카드 최소화
* 과도한 KPI 배치 지양
* 높은 정보 밀도보다 명확한 정보 계층 우선
* 중요한 변화만 시각적으로 강조

초기 화면에 모든 기능을 노출하지 않는다.

필터 및 세부 정보는 필요할 때 확장하는 Progressive Disclosure 방식을 권장한다.

---

## 13. 사용자 정의 필터

### 13.1 기본 필터

* Interest
* Data Source
* Time Range
* Node Type
* Industry
* Topic
* Relevance
* Mention Growth
* Relationship Strength
* New Issues
* Emerging Connections

### 13.2 스키마 기반 필터

AI가 새롭게 발견한 개념을 필터 선택지에 반영할 수 있어야 한다.

예를 들어 AI가 데이터센터 전력 공급 관련 이슈를 새롭게 식별하면 사용자는 이를 관심 필터에 추가할 수 있다.

다만 AI가 생성한 신규 분류는 검증 및 정규화 후 사용자에게 표시한다.

### 13.3 필터 저장

사용자는 필터 조합을 저장할 수 있다.

```json
{
  "view_name": "NVIDIA Emerging Issues",
  "interest": "NVIDIA",
  "depth": 2,
  "sources": [
    "dcinside",
    "naver"
  ],
  "filters": {
    "time_range": "7d",
    "new_nodes_only": true,
    "min_relevance": 0.8
  }
}
```

### 13.4 후속 활용

저장된 필터는 다음 기능으로 확장할 수 있다.

* 관측 화면
* 자동 알림
* 정기 리포트
* Shadow Trading 신호

단, 시각화 필터와 실제 매매 전략은 별개의 객체로 관리한다.

---

## 14. Signal Detection Engine

### 14.1 목적

관심사의 단순 언급량보다 이슈 구조의 변화를 탐지한다.

초기 신호 유형은 다음과 같다.

#### Attention Surge

관심도 급증.

#### Narrative Convergence

여러 이슈가 특정 개체로 집중되는 현상.

#### Relationship Emergence

새로운 의미 관계 등장.

#### Topic Migration

관심이 다른 주제로 이동하는 현상.

#### Narrative Reversal

기존 논조가 반대 방향으로 변화.

#### Persistent Issue

장기간 반복되는 이슈.

### 14.2 판단 기준

다음 요소를 활용한다.

* Velocity
* Persistence
* Connectivity
* Breadth
* Severity

최초에는 규칙 기반 탐지를 적용한다.

관측 데이터가 충분하지 않은 경우 정상 수준 대비 이상 여부를 단정하지 않는다.

### 14.3 경보 구조

```yaml
signal:
  type: relationship_emergence
  severity: attention
  node: NVIDIA
  related_topic: HBM Supply
  evidence_count: 5
  status: detected
```

경보는 미래 사건의 발생 확률이 아니라 현재 관찰된 변화의 중요도를 표현한다.

모든 경보에는 검토 가능한 근거가 필요하다.

---

## 15. Shadow Trading

### 15.1 목적

지식 그래프에서 발견한 정보가 실제 시장에서 유용한 신호인지 검증한다.

초기에는 실제 주문을 실행하지 않는다.

가상 자산으로 여러 시나리오를 동시에 운영한다.

### 15.2 테스트 전략

#### S1 — Attention Strategy

언급량 변화 기반.

#### S2 — Narrative Strategy

이슈 구조 변화 기반.

#### S3 — Graph Strategy

노드 연결성 변화 기반.

#### S4 — Community Strategy

미주갤 및 네이버 종토방 간 변화 비교.

#### S5 — Hybrid Strategy

커뮤니티 신호와 시장 가격·거래량 결합.

#### Baseline

SPY 보유, 현금 보유, 단순 가격 규칙 등 비교 전략.

### 15.3 평가 지표

* Total Return
* Benchmark Excess Return
* Maximum Drawdown
* Sharpe Ratio
* Trade Win Rate
* Average Trade Return
* Turnover
* Transaction Costs

실험 규칙을 변경하면 새로운 전략 버전으로 분리한다.

과거 성과를 소급 수정하지 않는다.

### 15.4 필수 원칙

* Paper Trading Only
* No Live Orders
* No Look-ahead Bias
* Realistic Execution Timing
* Transaction Cost Included
* Strategy Versioning
* Forward Testing

Shadow Trading은 핵심 지식 그래프가 안정적으로 작동한 다음 추가한다.

---

## 16. 데이터베이스 설계

### 16.1 기본 테이블

```text
interest_profiles
source_adapters
documents
document_metric_snapshots
nodes
node_aliases
claims
edges
edge_evidence
graph_events
wiki_revisions
saved_views
classification_feedback
```

### 16.2 테이블 역할

#### interest_profiles

사용자 관심사 및 자동 탐색 설정.

#### documents

원천 데이터 메타데이터.

#### nodes

지식 객체의 고유 정체성.

#### edges

노드 간 관계.

#### claims

원천 자료에서 추출된 주장.

#### edge_evidence

관계와 원천 근거 연결.

#### graph_events

시간에 따른 그래프 변화.

#### wiki_revisions

위키 문서의 버전.

#### saved_views

사용자 필터.

#### classification_feedback

AI 분류 및 관계 생성에 대한 평가.

### 16.3 데이터 모델 원칙

1. Node ID는 안정적으로 유지한다.
2. 동일 개체의 중복 생성을 방지한다.
3. Graph Events는 변경 이력을 보존한다.
4. Wiki는 DB를 기반으로 생성한다.
5. 사용자별 그래프는 공통 데이터의 서브그래프로 구성한다.
6. 시계열 복원에 필요한 정보는 삭제하거나 소급 변경하지 않는다.
7. 모든 AI 변경에는 모델·프롬프트·스키마 버전을 기록한다.

---

## 17. 기술 스택

#### Frontend

* React
* TypeScript
* Vite
* Tailwind CSS
* shadcn/ui

#### Graph Visualization

* Sigma.js
* Graphology

#### Backend

* Python
* FastAPI
* Pydantic

#### Database

* SQLite
* DuckDB

#### AI

* Claude Haiku 계열
* Optional Embedding Model
* Optional Lightweight Classifier

#### Scheduling

* Python Worker
* APScheduler 또는 동등한 작업 스케줄러

#### Deployment

* Local Development
* Staging Web App
* Production Web App
* Future PWA

MVP에서는 불필요한 인프라를 도입하지 않는다.

Neo4j, Kubernetes, 복잡한 다중 에이전트 프레임워크는 최초 구현의 필수 요소가 아니다.

---

## 18. GitHub Repository

```text
narrative-radar/
│
├── apps/
│   └── web/
│
├── backend/
│   ├── api/
│   ├── collectors/
│   ├── classifiers/
│   ├── normalization/
│   ├── discovery/
│   ├── ontology/
│   ├── graph/
│   ├── wiki/
│   ├── temporal/
│   ├── signals/
│   └── trading/
│
├── schemas/
│
├── tests/
│   ├── fixtures/
│   ├── unit/
│   └── integration/
│
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── DATA_SCHEMA.md
│   ├── DECISIONS.md
│   └── ROADMAP.md
│
├── .env.example
│
└── README.md
```

#### 공개 저장소 원칙

* 민감한 API 키 제외
* 개인 계정 정보 제외
* 데이터 이용 권한을 확보하지 않은 게시글 원문 제외
* 재현 가능한 테스트 데이터 제공
* 설치 및 실행 방법 문서화
* 기술적 의사결정 기록
* 실제 테스트 성능 공개
* 그래프 시각화 데모 포함

---

## 19. MVP 개발 로드맵

#### Phase 1 — Vertical Slice

목표:

게시글 하나가 지식 그래프 변화로 이어지는 전체 파이프라인을 구현한다.

```text
Input Document
     ↓
AI Classification
     ↓
Entity Resolution
     ↓
Node / Edge Generation
     ↓
Wiki Update
     ↓
Graph Visualization
```

이 단계에서는 합성 또는 사용이 허용된 데이터로 테스트한다.

#### Phase 2 — Temporal Engine

목표:

시간별 그래프 상태를 복원한다.

구현 항목:

* Graph Event Log
* Historical State
* Timeline Slider
* Playback Controls
* Wiki Version Synchronization

#### Phase 3 — Source Integration

목표:

미주갤과 네이버 종토방 데이터 입력 경로를 통합한다.

구현 항목:

* 소스별 어댑터
* 데이터 정규화
* 소스별 필터
* 댓글·게시글 활동량
* 중복 방지
* 수집 상태 모니터링

실제 라이브 연동은 이용 권한이 확인된 데이터 소스에 한해 활성화한다.

#### Phase 4 — Personalization

목표:

사용자 관심사에 따라 그래프를 자동 확장한다.

구현 항목:

* Interest Profile
* Depth Control
* Auto Expansion
* Node Approval
* Saved Filters

#### Phase 5 — Intelligence

목표:

새로운 이슈와 관계 변화를 탐지한다.

구현 항목:

* Signal Detection
* Emerging Issues
* Activity Changes
* Relationship Changes
* Explainable Alerts

#### Phase 6 — Shadow Trading

목표:

발견한 신호의 경제적 유용성을 검증한다.

구현 항목:

* Market Data Integration
* Paper Portfolio
* Strategy Definitions
* Virtual Orders
* Performance Evaluation
* Benchmark Comparison

---

## 20. 테스트 및 검증 기준

### 20.1 데이터 처리

* 동일 문서 재처리 시 중복 방지
* 종목 별칭 정규화 성공
* 노드 생성 정확성 검수
* 관계 추출 정확성 검수
* 근거 출처 연결 유지
* 댓글 수 중복 집계 방지

### 20.2 개인화

* 최대 탐색 깊이 준수
* 자동 확장 조건 준수
* 기존 노드와 중복 방지
* 사용자 관심사 변경 반영

### 20.3 Temporal Graph

* 과거 시점 복원
* 미래 정보 누출 방지
* Graph Event 재생
* Wiki History 동기화
* 노드 위치 안정성

### 20.4 사용자 경험

* 노드 클릭 시 위키 표시
* 엣지 클릭 시 연결 근거 표시
* 시간 슬라이더 정상 동작
* 데이터 소스 필터 정상 동작
* 사용자 필터 저장
* 그래프 탐색 시 과도한 시각적 혼잡 방지

### 20.5 테스터 평가

테스터는 다음을 평가할 수 있어야 한다.

* 노드가 유의미한가?
* 관계가 타당한가?
* 새로운 정보를 발견했는가?
* 위키가 이해하기 쉬운가?
* 시간 재생이 변화 파악에 도움이 되는가?
* 누락된 중요한 이슈가 있는가?

피드백은 모델 및 스키마 버전과 함께 저장한다.

---

## 21. 첫 번째 개발 목표

최초 개발의 성공 기준은 다음과 같다.

사용자가 웹 브라우저에서 NVIDIA를 선택한다.

초기 그래프에는 NVIDIA 노드가 표시된다.

데이터가 분석되면서 관련 이슈 노드가 자동으로 생성된다.

새로운 정보가 들어오면 기존 노드와 관계가 갱신된다.

사용자는 시간 슬라이더를 이동해 이슈의 변화를 확인한다.

노드를 클릭하면 AI가 작성한 위키가 나타난다.

위키에서는 해당 정보의 근거를 확인할 수 있다.

사용자는 관심 없는 노드를 필터링하거나 자동 확장 후보를 거절할 수 있다.

여기까지 정상 작동하면 MVP V0.1의 핵심 성공으로 판정한다.

데이터 수집 권한이 확보되지 않은 소스는 테스트 모드로 표시하고, 라이브 연동에 성공한 것처럼 표현하지 않는다.

---

## 22. 개발 원칙

### 22.1 기능 우선순위

다음 우선순위를 따른다.

1. 정확한 데이터 구조
2. 신뢰할 수 있는 노드 정규화
3. 근거 있는 관계 생성
4. 정확한 시간 이력
5. 편리한 그래프 탐색
6. 안정적인 UI
7. 시각적 애니메이션
8. 부가 기능

### 22.2 복잡성 통제

초기부터 과도한 기능을 추가하지 않는다.

* 불필요한 대시보드 카드 생성 금지
* 의미 없는 KPI 노출 금지
* 중복 정보 표시 금지
* 필요하지 않은 에이전트 추가 금지
* 검증되지 않은 예측 점수 생성 금지
* 복잡한 인프라의 조기 도입 금지

### 22.3 핵심 구현 철학

데이터는 구조화하고, 지식은 연결하며, 변화는 시간으로 설명한다.

---

## 23. Claude Code 실행 지침

이 문서는 Narrative Radar 개발의 기준 PRD다.

개발 시 다음 순서를 따른다.

#### Step 1

프로젝트 구조와 기본 기술 스택을 준비한다.

#### Step 2

공통 데이터 스키마를 정의한다.

#### Step 3

테스트 문서를 사용하여 AI 분류 파이프라인을 구현한다.

#### Step 4

Entity Resolution과 Graph Builder를 구현한다.

#### Step 5

Living Wiki 생성 및 갱신 기능을 구현한다.

#### Step 6

Graph Events를 저장하고 시간별 그래프 상태를 복원한다.

#### Step 7

React 기반 그래프 시각화를 구현한다.

#### Step 8

시간 재생 인터페이스를 구현한다.

#### Step 9

미주갤 및 네이버 종토방 데이터 어댑터를 연결한다.

#### Step 10

사용자 관심사 설정과 자동 확장 기능을 구현한다.

#### Step 11

통합 테스트와 시각적 검증을 진행한다.

#### Step 12

README 및 GitHub 공개 준비를 진행한다.

개발 도중 설계 변경이 필요하면 변경 이유를 DECISIONS.md에 기록한다.

기능을 추가하는 것보다 실제로 작동하는 최소 기능의 완성도를 우선한다.

---

## 24. 최종 제품 비전

Narrative Radar는 데이터 수집기나 주식 정보 대시보드가 아니다.

사용자가 관심사 하나를 등록하면 AI가 지속적으로 관련 정보를 탐색하고, 새로운 개체와 이슈를 발견하며, 그 관계를 시간에 따라 갱신하는 개인화 인텔리전스 플랫폼이다.

금융 분야에서는 집단심리 관측과 Shadow Trading에 활용할 수 있다.

기업에서는 HR 및 조직 이슈 조기경보에 활용할 수 있다.

게임 분야에서는 사용자 불만과 신규 트렌드 발견에 활용할 수 있다.

소비자 분야에서는 브랜드 평판과 잠재 수요 발견에 활용할 수 있다.

모든 응용 분야는 동일한 Knowledge Discovery Engine을 공유한다.

#### Core Value Proposition

From fragmented conversations to evolving intelligence.

파편화된 대화를 지속적으로 진화하는 지식으로 전환한다.

#### Ultimate Vision

Personal Intelligence Graph

사용자마다 다른 관심사를 중심으로 성장하는 개인화된 지식 네트워크.

#### First Milestone

NVIDIA → Automatic Wiki → Temporal Knowledge Graph → Windy-style Replay

이 전체 과정을 실제 웹앱에서 구현하는 것이 첫 번째 목표다.

---

END OF PRD

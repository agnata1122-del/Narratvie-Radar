# 금융·투자 팩 보충 지침 (`finance.v1`)

공통 지침(`classification_v2.md`)을 먼저 읽고, 투자 커뮤니티 글에는 아래를 더한다.

## 키

- **상장사는 `국가:티커`**: `US:NVDA`, `US:AMD`, `KR:000660`(SK하이닉스), `KR:005930`(삼성전자), `TW:2330`(TSMC). 티커를 모르면 지어내지 말고 `ORG:슬러그`를 쓴다.
- 비상장 기업은 `ORG:슬러그` (예전 데이터의 `COMPANY:슬러그`도 그대로 쓴다).
- 산업은 `INDUSTRY:슬러그` (예: `INDUSTRY:semiconductors`), 유형은 `topic`.

## 태도·방향을 읽는 법

- `stance`: 관심사 종목에 대해 `positive` = 강세(오를 것), `negative` = 약세(내릴 것), `mixed` = 둘 다, `neutral` = 방향 없음.
- `polarity`: 주어가 관심사 종목의 성장 근거면 `enabler`, 제약 요인(공급 부족, 규제, 경쟁 심화 등)이면 `constraint`.
- 가격 예측 숫자("목표가 200")는 주장 대상이 아니다. 그 근거가 된 관계만 뽑는다.

## 은어

투자 커뮤니티의 은어는 원문 표기를 `name`에 그대로 두고, 확실할 때만 기존 키로 잇는다.
- 예: "엔비" → NVIDIA, "하닉" → SK하이닉스, "삼전" → 삼성전자, "젠슨황"·"가죽잠바" → 인물 노드(`PERSON:jensen-huang`, 공인).
- 처음 보는 은어가 글의 핵심이면 `needs_review: true`, `review_reason`에 은어를 적는다. 확인된 은어는 별칭 사전에 추가된다.

## 예시 (형식만 보여주는 가상 문장)

입력 `text`: "HBM 공급이 막히면 엔비 출하도 밀린다는 얘기가 많네"

```json
{"document_id": "doc_...", "content_hash": "...", "output": {
  "relevance": 0.9, "is_noise": false, "language": "ko",
  "entities": [
    {"name": "엔비", "type": "organization", "canonical_key": "US:NVDA"},
    {"name": "HBM", "type": "technology", "canonical_key": "TECH:hbm"}
  ],
  "stance": "negative",
  "claims": [
    {"subject": "HBM", "predicate": "AFFECTS", "object": "엔비",
     "polarity": "constraint", "stance": "negative", "evidence_status": "speculation",
     "excerpt": "HBM 공급이 막히면 엔비 출하도 밀린다는 얘기가 많네",
     "narrative_key": null,
     "narrative_proposition": "HBM 공급이 NVIDIA 출하의 제약 요인이다",
     "narrative_role": "supports"}
  ],
  "needs_review": false, "review_reason": null
}}
```

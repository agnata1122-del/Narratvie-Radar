# 금융·투자 팩 보충 지침 (`finance.v2`)

공통 지침(`classification_v2.md`)을 먼저 읽고, 투자 커뮤니티 글에는 아래를 더한다.

## 키

- **상장사는 등록된 표준 식별자를 먼저 쓴다**: `context.json` 온톨로지와 글의 `known_nodes`에 있는 키가 종목 마스터다. 같은 회사면 반드시 그 키를 쓴다(`US:NVDA`, `US:MU`, `KR:000660` SK하이닉스, `KR:005930` 삼성전자 등).
- 마스터에 없는 상장사는 주 상장 시장의 `국가:티커`를 확실히 알 때만 쓴다(예: `TW:2330` TSMC, `US:MSFT`). **확실하지 않으면 티커를 지어내지 말고** `canonical_key: null`로 두고 `needs_review: true`, `review_reason`에 "상장사 식별자 확인 필요: <이름>"을 적는다.
- **같은 회사를 `ORG:`와 티커 키로 따로 만들지 않는다.** 상장사에는 `ORG:`를 쓰지 않는다.
- 비상장 기업은 `ORG:슬러그` (예전 데이터의 `COMPANY:슬러그`도 그대로 쓴다). 상장 모회사의 사업부·자회사(예: Google, AWS)는 모회사와 다른 대상이므로 `ORG:슬러그`로 둔다.
- 산업은 `INDUSTRY:슬러그` (예: `INDUSTRY:semiconductors`), 유형은 `topic`.

## 태도·방향을 읽는 법

- `stance`: 관심사 종목에 대해 `positive` = 강세(오를 것), `negative` = 약세(내릴 것), `mixed` = 둘 다, `neutral` = 방향 없음.
- `polarity`: 주어가 **목적어**를 돕는가(`enabler`) 막는가(`constraint`: 공급 부족, 규제, 경쟁 심화 등). 관심사 종목이 아니라 그 관계의 목적어가 기준이다 (v3 지침과 같다).
- 가격 예측 숫자("목표가 200")는 주장 대상이 아니다. 그 근거가 된 관계만 뽑는다.

## 관계를 만들지 않는 경우

- **주가·수익률의 상대 성과**("A가 B보다 많이 올랐다"), **단순 동시 언급**, **성능·가격 비교만 있는 문장**("A가 B보다 느리다", "A는 B에 안 된다")으로는 `COMPETES_WITH`를 포함한 어떤 관계도 만들지 않는다. 경쟁은 같은 고객·시장을 두고 다툰다는 주장이 있을 때만 쓴다(예: "하이퍼스케일러가 자체 칩으로 엔비디아 구매를 대신한다").
- 명확한 의미 관계가 없으면 `RELATED_TO`로 대신 넣지 말고 **관계를 생략한다**(공통 지침의 `RELATED_TO`보다 이 규칙이 우선한다). 예정·협의 중인 공급("공급을 협의 중")처럼 관계가 아직 주장되지 않았으면 생략한다.

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

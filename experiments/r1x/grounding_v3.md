# 근거 검증 지침 v3 초안 (`grounding.v3-draft`, R1-X 2단계)

> 추출(1단계)을 한 대화와 **다른 새 대화**에서 돌린다. 같은 맥락이 만든 오류를 같은 맥락이 확인하지 않게 하기 위해서다.
> 추출 결과를 고치지 않는다. 항목마다 판정만 붙인다.
> 2026-10-18 소유자 검토 반영: 발췌가 뒷받침하지 못하면 원문 전체에 근거가 있어도 review, 출처 성격만으로 확장하지 않음.

## 입력

글마다 원문(`text`, `parent_text`)과 1단계 출력의 `events`, `causal_links`, `claims`.

## 판정

항목마다 **제출된 발췌**와 **원문 전체**를 따로 본다.

| 판정 | 뜻 |
|---|---|
| `entailed` | 제출된 발췌가 그 항목을 그대로 뒷받침한다. 주어·목적어·변수·방향·양태·부정·근거 수준이 원문과 같다 |
| `partial` | 큰 틀은 맞지만 하나가 어긋나거나, **발췌는 뒷받침하지 못하고 원문의 다른 곳에만 근거가 있다** |
| `not_entailed` | 원문 어디에도 근거가 없다(비교·인접·선후·상관을 관계나 인과로 만든 경우 포함) |

- `partial`과 `not_entailed`에는 `issue` 하나를 붙인다: `excerpt_mismatch`(근거가 발췌 밖에 있음) · `modality` · `negation` · `supply_stage` · `evidence_level`(예: `asserted`를 `mechanism`으로) · `wrong_subject` · `wrong_object` · `comparison_as_relation` · `adjacency_as_causation` · `temporal_as_causation` · `component_as_part_of` · `event_compressed` · `other`.
- `excerpt_mismatch`이면 `note`에 원문의 근거 문장을 적는다. 판정은 `partial`(review)이고 통과시키지 않는다.
- 그럴듯함은 검증이 아니다. 배경지식으로 맞다고 알아도 원문이 말하지 않으면 `not_entailed`.

## 출력

```json
{"document_id": "...", "verdicts": [
  {"kind": "event|causal_link|claim", "index": 0, "verdict": "entailed|partial|not_entailed",
   "issue": null, "note": ""}
]}
```

## 반영 규칙 (실험에서 쓰는 값)

- `not_entailed` → 버린다. `partial` → review. `entailed` → 통과.
- 그래프 자동 확장 후보(탐색 가설과 구분):
  - 인과 연결: `entailed`이고 `evidence_level`이 `mechanism` 또는 `asserted`(원문의 명시적 인과 주장)인 것만. `speculative`는 탐색 가설.
  - 관계(`claims`): `entailed`이고 `modality: actual`, `negated: false`인 것만.
  - **`attribution`(`reported`·`official`)은 확장 조건이 아니다.** 출처 성격만으로 자동 확장하지 않는다.
  - 기존 독립 근거 기준(D6: 서로 다른 작성자·출처 2곳 이상)을 그대로 적용한다. 위 조건은 그 위에 더하는 거름이다.

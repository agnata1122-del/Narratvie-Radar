# 근거 검증 지침 v3 초안 (`grounding.v3-draft`, R1-X 2단계)

> 추출(1단계)을 한 대화와 **다른 새 대화**에서 돌린다. 같은 맥락이 만든 오류를 같은 맥락이 확인하지 않게 하기 위해서다.
> 추출 결과를 고치지 않는다. 항목마다 판정만 붙인다.

## 입력

글마다 원문(`text`, `parent_text`)과 1단계 출력의 `events`, `causal_links`, `claims`.

## 판정

항목마다 원문 **전체**를 읽고, 그 항목이 원문에서 함의되는지 하나를 고른다.

| 판정 | 뜻 |
|---|---|
| `entailed` | 원문이 그대로 말한다. 발췌가 맞고 주어·목적어·방향·양태가 원문과 같다 |
| `partial` | 큰 틀은 맞지만 하나가 어긋난다(양태: 예정을 실제로, 공급 단계: 인증을 납품으로, 근거 수준이 과장됨, 주어가 실제 행위자가 아님) |
| `not_entailed` | 원문이 말하지 않는다(비교·인접·동시 언급을 관계나 인과로 만든 경우 포함) |

- `partial`과 `not_entailed`에는 `issue` 하나를 붙인다: `modality` · `supply_stage` · `evidence_level` · `wrong_subject` · `wrong_object` · `comparison_as_relation` · `adjacency_as_causation` · `component_as_part_of` · `event_compressed` · `other`.
- 그럴듯함은 검증이 아니다. 배경지식으로 맞다고 알아도 원문이 말하지 않으면 `not_entailed`.
- 발췌가 아니라 원문 전체에 근거가 있으면 `entailed`로 하고 `note`에 근거 문장을 적는다(예: 같은 글의 출하 발표).

## 출력

```json
{"document_id": "...", "verdicts": [
  {"kind": "event|causal_link|claim", "index": 0, "verdict": "entailed|partial|not_entailed",
   "issue": null, "note": ""}
]}
```

## 반영 규칙 (실험에서 쓰는 값)

- `not_entailed` → 버린다. `partial` → review. `entailed` → 통과.
- 그래프 자동 확장 후보: `entailed`이면서 근거 수준이 `mechanism`이거나 `attribution`이 `reported`/`official`인 것만. 나머지는 탐색 가설.

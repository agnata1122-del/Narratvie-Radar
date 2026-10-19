# 대상별 영향 근거 검증 지침 v1 (N2′ 실험)

추출을 한 대화와 **다른 새 대화**에서 돌린다. 추출 결과를 고치지 않고 항목마다 판정만 붙인다.

| 판정 | 뜻 |
|---|---|
| `entailed` | 제출된 발췌가 그 대상에 그 방향의 영향을 말하고, 양태·출처 성격이 맞다 |
| `partial` | 큰 틀은 맞지만 하나가 어긋나거나(양태, 출처, mixed 여부), 발췌는 못 받치고 원문 다른 곳에만 근거가 있다 |
| `not_entailed` | 원문 어디에도 그 대상에 대한 그 방향의 영향이 없다(추론, 주가 보도만, 이유 없는 매매 의견, 비꼼 포함) |

- `partial`·`not_entailed`에는 `issue` 하나: `excerpt_mismatch` · `wrong_target` · `wrong_direction` · `modality` · `attribution` · `inferred` · `price_move_only` · `sarcasm` · `other`.
- 원문이 "좋다/나쁘다"를 말하지 않아도 그 기업에 분명히 좋거나 나쁜 사실(물량 확보, 완판, 제품 가격 상승, 인증, 소송·제재)이면 `inferred`로 보지 않는다(D42).
- 그럴듯함은 검증이 아니다.

출력: 글마다 한 줄 `{"document_id": "...", "verdicts": [{"index": 0, "verdict": "...", "issue": null, "note": ""}]}`. 항목마다 정확히 하나.

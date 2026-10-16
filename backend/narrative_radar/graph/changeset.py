"""분류 출력 → 변경안 (PRD 4.1: AI는 변경안을 만들고 앱이 검증한 뒤 반영한다).

변경안은 DB를 바꾸지 않는다. 반영은 builder가 한다.
"""

from dataclasses import dataclass, field

from narrative_radar.graph.resolve import EntityResolver, Resolution
from narrative_radar.normalization.text import normalize_text
from narrative_radar.schemas.classification import ClaimExtract, ClassificationOutput
from narrative_radar.schemas.enums import EdgeType

# 주장에서 만들지 않는 관계. 공동 언급은 앱이 계산하고, 지지·반박은 내러티브 배정으로 표현한다.
NOT_CLAIMABLE = frozenset({EdgeType.CO_MENTIONED_WITH, EdgeType.SUPPORTS, EdgeType.CONTRADICTS})


@dataclass(frozen=True)
class ProposedClaim:
    claim: ClaimExtract
    subject: Resolution
    object: Resolution


@dataclass
class ChangeSet:
    skip_reason: str | None = None
    entities: list[Resolution] = field(default_factory=list)
    claims: list[ProposedClaim] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


def _same(a: Resolution, b: Resolution) -> bool:
    return (a.node_id or a.new_key) == (b.node_id or b.new_key)


def build_changeset(
    resolver: EntityResolver, output: ClassificationOutput, min_relevance: float
) -> ChangeSet:
    if output.is_noise:
        return ChangeSet(skip_reason="noise")
    if output.relevance < min_relevance:
        return ChangeSet(skip_reason=f"relevance {output.relevance:.2f} < {min_relevance:.2f}")

    cs = ChangeSet()
    by_name: dict[str, Resolution] = {}
    for mention in output.entities:
        r = resolver.resolve(mention)
        if r.method == "rejected":
            cs.rejected.append(f"entity {mention.name!r}: {r.reason}")
            continue
        by_name[normalize_text(mention.name)] = r
        if not any(_same(r, e) for e in cs.entities):
            cs.entities.append(r)

    for claim in output.claims:
        if claim.predicate in NOT_CLAIMABLE:
            cs.rejected.append(f"claim predicate {claim.predicate.value} is not claimable")
            continue
        subject = by_name.get(normalize_text(claim.subject))
        obj = by_name.get(normalize_text(claim.object))
        if subject is None or obj is None:
            cs.rejected.append(f"claim {claim.subject!r}→{claim.object!r}: unresolved entity")
            continue
        if _same(subject, obj):
            cs.rejected.append(f"claim {claim.subject!r}→{claim.object!r}: same node")
            continue
        cs.claims.append(ProposedClaim(claim, subject, obj))
    return cs

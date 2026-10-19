"""R1 검증 세트 내보내기 (docs/EXPERIMENTS.md "R1", DECISIONS D39).

v3로 다시 추출·반영한 그래프에서 확장에 관련된 것을 꺼낸다.
- edges.jsonl: 공동 언급을 뺀 의미 관계 전부. 상태·근거 단계·확장 경로 사용 여부,
  근거 글(최대 3개).
- tree.jsonl: 관심사 트리 노드(포함·검토 대기)와 루트까지의 최단 경로.
- duplicates.jsonl: 트리 노드가 들어 있는 중복 후보 묶음.
- checks.json: 기계로 잴 수 있는 기준 (경로가 있는지, 발췌가 원문 그대로인지, 중복 후보 비율).

원문 뒷받침 여부는 사람이·AI가 판단한다. 이 스크립트는 판단하지 않는다.
출력에 원문이 들어가므로 비공개 데이터 저장소에만 둔다.
"""

import argparse
import json
from collections import deque
from pathlib import Path

import sqlalchemy as sa

from narrative_radar.classifiers.session import _source_text
from narrative_radar.core.config import get_settings
from narrative_radar.db.models import (
    Claim,
    ClassificationRun,
    Document,
    Edge,
    EdgeEvidence,
    InterestProfile,
    Node,
)
from narrative_radar.db.session import make_engine, make_session_factory
from narrative_radar.discovery.expansion import expansion_edges, latest_decisions
from narrative_radar.graph.builder import independent_evidence
from narrative_radar.graph.evidence import edge_tiers
from narrative_radar.graph.merge import duplicate_candidates
from narrative_radar.schemas.enums import EdgeStatus, EdgeType, ProfileNodeStatus

MAX_EVIDENCE = 3
TEXT_CHARS = 2500


def _path(adj: dict[str, list[tuple[str, str]]], root: str, target: str) -> list[str] | None:
    """루트에서 target까지 edge_id 목록 (방향 무시 최단거리)."""
    prev: dict[str, tuple[str, str] | None] = {root: None}
    queue = deque([root])
    while queue:
        node = queue.popleft()
        if node == target:
            break
        for nxt, edge_id in adj.get(node, ()):
            if nxt not in prev:
                prev[nxt] = (node, edge_id)
                queue.append(nxt)
    if target not in prev:
        return None
    out, node = [], target
    while prev[node] is not None:
        node, edge_id = prev[node]  # type: ignore[misc]
        out.append(edge_id)
    return out[::-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--profile", help="관심사 이름 (비우면 첫 관심사)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    session = make_session_factory(make_engine(get_settings().database_url))()

    q = sa.select(InterestProfile)
    if args.profile:
        q = q.where(InterestProfile.name == args.profile)
    profile = session.scalars(q).first()
    nodes = {n.node_id: n for n in session.scalars(sa.select(Node))}
    root = session.scalar(sa.select(Node).where(Node.canonical_key == profile.root_canonical_key))

    edges = session.scalars(
        sa.select(Edge).where(Edge.relation_type != EdgeType.CO_MENTIONED_WITH)
    ).all()
    tiers = edge_tiers(session, [e.edge_id for e in edges])
    expanding = {e for _, _, e in expansion_edges(session, [EdgeStatus.CONFIRMED])}
    reaching = {
        e for _, _, e in expansion_edges(session, [EdgeStatus.CONFIRMED, EdgeStatus.CANDIDATE])
    }

    texts: dict[str, str] = {}
    excerpt_ok = excerpt_total = 0
    with (args.out / "edges.jsonl").open("w", encoding="utf-8") as f:
        for e in edges:
            rows = session.execute(
                sa.select(Claim, ClassificationRun.schema_version)
                .join(EdgeEvidence, EdgeEvidence.claim_id == Claim.claim_id)
                .join(
                    ClassificationRun,
                    ClassificationRun.classification_id == Claim.classification_id,
                )
                .where(EdgeEvidence.edge_id == e.edge_id)
                .order_by(Claim.created_at)
            ).all()
            evidence = []
            for claim, schema in rows:
                doc = session.get(Document, claim.document_id)
                text = texts.setdefault(doc.document_id, _source_text(session, doc))
                ok = claim.excerpt in text
                excerpt_ok += ok
                excerpt_total += 1
                if len(evidence) < MAX_EVIDENCE:
                    evidence.append(
                        {
                            "document_id": doc.document_id,
                            "schema_version": schema,
                            "subject": claim.subject_text,
                            "object": claim.object_text,
                            "evidence_status": claim.evidence_status.value,
                            "excerpt": claim.excerpt,
                            "excerpt_verbatim": ok,
                            "text": text[:TEXT_CHARS],
                        }
                    )
            src, dst = nodes[e.source_node_id], nodes[e.target_node_id]
            rec = {
                "edge_id": e.edge_id,
                "source": src.canonical_key,
                "source_label": src.label,
                "relation": e.relation_type.value,
                "target": dst.canonical_key,
                "target_label": dst.label,
                "status": e.status.value,
                "tier": tiers[e.edge_id].value,
                "independent_evidence": independent_evidence(session, e.edge_id),
                "claims": len(rows),
                "legacy_v2_only": bool(rows) and all(s != "extraction.v3" for _, s in rows),
                "used_for_admission": e.edge_id in expanding,
                "used_for_reach": e.edge_id in reaching,
                "evidence": evidence,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    adj: dict[str, list[tuple[str, str]]] = {}
    for a, b, edge_id in expansion_edges(session, [EdgeStatus.CONFIRMED, EdgeStatus.CANDIDATE]):
        adj.setdefault(a, []).append((b, edge_id))
        adj.setdefault(b, []).append((a, edge_id))
    edge_by_id = {e.edge_id: e for e in edges}
    decisions = latest_decisions(session, profile.profile_id)
    tree_keys, with_path = set(), 0
    tree = [
        (nid, st)
        for nid, st in decisions.items()
        if st in (ProfileNodeStatus.ADMITTED, ProfileNodeStatus.PENDING_REVIEW)
        and nid != root.node_id
    ]
    with (args.out / "tree.jsonl").open("w", encoding="utf-8") as f:
        for nid, st in tree:
            path = _path(adj, root.node_id, nid)
            with_path += path is not None
            tree_keys.add(nodes[nid].canonical_key)
            hops = []
            for x in path or []:
                e = edge_by_id[x]
                hops.append(
                    f"{nodes[e.source_node_id].label} —{e.relation_type.value}→ "
                    f"{nodes[e.target_node_id].label}"
                )
            rec = {
                "node": nodes[nid].canonical_key,
                "label": nodes[nid].label,
                "decision": st.value,
                "path_edge_ids": path,
                "path": hops,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    groups = [g for g in duplicate_candidates(session) if tree_keys & {k for k, _ in g}]
    in_dup = {k for g in groups for k, _ in g} & tree_keys
    with (args.out / "duplicates.jsonl").open("w", encoding="utf-8") as f:
        for g in groups:
            f.write(
                json.dumps([{"key": k, "label": lab} for k, lab in g], ensure_ascii=False) + "\n"
            )

    checks = {
        "semantic_edges": len(edges),
        "tree_nodes": len(tree),
        "tree_nodes_with_path": with_path,
        "claims_excerpt_verbatim": f"{excerpt_ok}/{excerpt_total}",
        "tree_nodes_in_duplicate_candidates": f"{len(in_dup)}/{len(tree_keys)}",
    }
    (args.out / "checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=1))
    print(json.dumps(checks, ensure_ascii=False))


if __name__ == "__main__":
    main()

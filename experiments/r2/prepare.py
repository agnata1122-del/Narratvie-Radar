"""R2 재생용 사본 만들기 (docs/EXPERIMENTS.md "R2").

원본 DB에서 글·원문·분류·시세 같은 입력만 새 DB로 옮기고 그래프는 비운다.
관심사 루트와 소유자가 넣은 시작 노드(depth 1, 사람이 넣은 결정)는 재생 시작 시각으로 다시 넣는다.
자동 확장이 넣은 노드는 옮기지 않는다 (재생이 다시 정한다).

사용: python experiments/r2/prepare.py SRC.db DST.db --seed-at 2025-10-16
"""

import argparse
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from narrative_radar.core.clock import FixedClock
from narrative_radar.db.migrate import upgrade_to_head
from narrative_radar.db.models import InterestProfile
from narrative_radar.db.seed import seed_defaults
from narrative_radar.db.session import make_engine, make_session_factory
from narrative_radar.discovery.curation import admit_node
from narrative_radar.ingest.runs import finish_run, start_run
from narrative_radar.schemas.enums import NodeType, RunKind, RunStatus

# 그래프가 아닌 입력 표 (외래 키 순서)
INPUTS = [
    "source_adapters",
    "pipeline_runs",
    "documents",
    "raw_documents",
    "document_comments",
    "document_metric_snapshots",
    "source_health",
    "classification_runs",
    "site_policies",
    "discovered_urls",
    "fetch_logs",
    "control_flags",
    "price_bars",
]
PROFILE_SETTINGS = [
    "max_depth",
    "auto_expand",
    "max_new_nodes_per_day",
    "minimum_independent_evidence",
    "require_relevance",
    "allow_depth_overflow",
]
AUTO_REASONS = ("confirmed path", "reachable only", "generic node type", "root interest")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--seed-at", required=True, help="루트·시작 노드를 넣을 날 (UTC, YYYY-MM-DD)")
    args = ap.parse_args()
    if args.dst.exists():
        raise SystemExit(f"{args.dst} already exists")
    url = f"sqlite:///{args.dst}"
    upgrade_to_head(url)

    src = sqlite3.connect(args.src)
    profile = dict(
        zip(
            ["name", "root", *PROFILE_SETTINGS],
            src.execute(
                f"select name, root_canonical_key, {', '.join(PROFILE_SETTINGS)} "
                "from interest_profiles where parent_profile_id is null"
            ).fetchone(),
            strict=True,
        )
    )
    seeds = src.execute(
        "select n.canonical_key, n.label, n.node_type, p.depth, p.reason, n.node_id "
        "from profile_nodes p join nodes n using(node_id) where p.depth >= 1"
    ).fetchall()
    seeds = [s for s in seeds if not s[4].startswith(AUTO_REASONS)]
    aliases = {
        key: [a for (a,) in src.execute("select alias from node_aliases where node_id = ?", (nid,))]
        for key, _, _, _, _, nid in seeds
    }
    src.close()

    dst = sqlite3.connect(args.dst)
    dst.execute("attach database ? as src", (str(args.src),))
    dst.execute("pragma foreign_keys = off")
    for table in INPUTS:
        dst.execute(f"insert into main.{table} select * from src.{table}")
    dst.execute(
        "update main.documents set processed_at = null, available_at = null, "
        "derivation_group_id = null"
    )
    dst.commit()
    dst.execute("detach database src")
    dst.close()

    seed_at = datetime.fromisoformat(args.seed_at).replace(tzinfo=UTC)
    clock = FixedClock(seed_at)
    factory = make_session_factory(make_engine(url))
    with factory.begin() as session:
        seed_defaults(session, clock)
        p = session.scalars(sa.select(InterestProfile)).one()
        for k in PROFILE_SETTINGS:
            setattr(p, k, profile[k])
        run = start_run(session, clock, RunKind.SETUP, params={"r2_prepare": str(args.src)})
        for key, label, node_type, depth, reason, _ in seeds:
            admit_node(
                session,
                clock,
                run.run_id,
                p,
                key,
                label,
                NodeType(node_type),
                aliases[key],
                depth,
                reason,
            )
        finish_run(run, clock.now(), RunStatus.SUCCEEDED)
    print(f"seeds={[s[0] for s in seeds]} settings={profile}")


if __name__ == "__main__":
    main()

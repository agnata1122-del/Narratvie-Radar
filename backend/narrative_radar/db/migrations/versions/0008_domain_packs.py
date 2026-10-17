"""domain packs: generic node types, stance, polarity; profile domain

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-17 09:00:00

노드 유형·태도·방향을 분야와 무관한 값으로 바꾸고, 관심사에 도메인 팩을 붙인다 (DECISIONS D22).
추가 전용 테이블(classification_runs 등)의 예전 값은 그대로 두고, 읽을 때 바꾼다
(schemas/classification.py).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (테이블, 열, 예전 값, 새 값)
RENAMES = [
    ("nodes", "node_type", "company", "organization"),
    ("nodes", "node_type", "industry", "topic"),
    ("claims", "stance", "bullish", "positive"),
    ("claims", "stance", "bearish", "negative"),
    ("claims", "polarity", "growth_driver", "enabler"),
]


def _rename(rows: list[tuple[str, str, str, str]]) -> None:
    for table, column, old, new in rows:
        op.execute(
            sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old").bindparams(
                old=old, new=new
            )
        )


def upgrade() -> None:
    _rename(RENAMES)
    # 열 추가만 한다 (batch 재생성을 피해 트리거에 영향이 없게)
    op.add_column(
        "interest_profiles",
        sa.Column("domain", sa.String(length=32), server_default="general", nullable=False),
    )
    # 지금까지의 관심사(NVIDIA)는 금융 가정 위에서 만들어졌다
    op.execute(sa.text("UPDATE interest_profiles SET domain = 'finance'"))


def downgrade() -> None:
    # batch 재생성은 이 테이블을 참조하는 외래 키 때문에 실패한다.
    # SQLite 3.35+의 DROP COLUMN을 쓴다.
    op.execute(sa.text("ALTER TABLE interest_profiles DROP COLUMN domain"))
    # 되돌릴 때 새 유형(인물·제품·장소)은 예전 값이 없어 주제(topic)로 둔다
    _rename([(t, c, new, old) for t, c, old, new in RENAMES if old != "industry"])
    op.execute(
        sa.text(
            "UPDATE nodes SET node_type = 'topic' WHERE node_type IN ('person', 'product', 'place')"
        )
    )

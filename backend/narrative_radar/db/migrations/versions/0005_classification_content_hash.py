"""classification content hash

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 테이블을 다시 만들지 않도록 ALTER TABLE ADD COLUMN으로 추가한다 (추가 전용 트리거 보존).
    # SQLite는 NOT NULL 컬럼을 추가할 때 기본값이 필요하다.
    op.add_column(
        "classification_runs",
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    with op.batch_alter_table("classification_runs", schema=None) as batch_op:
        batch_op.drop_column("content_hash")
    for action in ("UPDATE", "DELETE"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_classification_runs_no_{action.lower()}")
        op.execute(
            f"CREATE TRIGGER trg_classification_runs_no_{action.lower()} "
            f"BEFORE {action} ON classification_runs "
            "BEGIN SELECT RAISE(ABORT, 'classification_runs is append-only'); END"
        )

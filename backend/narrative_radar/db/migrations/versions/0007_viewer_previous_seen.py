"""viewer previous_seen_at

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-16 15:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from narrative_radar.db import types as nr_types

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 열 추가만 한다 (batch 재생성을 피해 다른 테이블의 트리거에 영향이 없게)
    op.add_column(
        "viewers", sa.Column("previous_seen_at", nr_types.UTCDateTime(length=32), nullable=True)
    )


def downgrade() -> None:
    with op.batch_alter_table("viewers") as batch:
        batch.drop_column("previous_seen_at")

"""profile branches: parent profile and origin

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-17 12:00:00

관심사 그래프의 노드에서 파고들어 새 관심사(가지)를 만든다 (DECISIONS D23).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite는 기존 테이블에 외래 키 제약을 나중에 붙일 수 없어 열 정의에 함께 쓴다
    op.execute(
        sa.text(
            "ALTER TABLE interest_profiles ADD COLUMN parent_profile_id VARCHAR(40) "
            "REFERENCES interest_profiles (profile_id)"
        )
    )
    op.create_index(
        op.f("ix_interest_profiles_parent_profile_id"),
        "interest_profiles",
        ["parent_profile_id"],
    )
    op.add_column(
        "interest_profiles",
        sa.Column("origin", sa.String(length=32), server_default="registered", nullable=False),
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_interest_profiles_parent_profile_id"), table_name="interest_profiles")
    # batch 재생성은 이 테이블을 참조하는 외래 키 때문에 실패한다.
    # SQLite 3.35+의 DROP COLUMN을 쓴다.
    op.execute(sa.text("ALTER TABLE interest_profiles DROP COLUMN origin"))
    op.execute(sa.text("ALTER TABLE interest_profiles DROP COLUMN parent_profile_id"))

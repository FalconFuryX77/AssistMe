"""Add persisted session guides and their ordered steps.

Revision ID: d4f0a8c6b219
Revises: c1a4e9d2b7f3
Create Date: 2026-10-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4f0a8c6b219"
down_revision: Union[str, None] = "c1a4e9d2b7f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type() -> sa.types.TypeEngine:
    return sa.Uuid(as_uuid=False, native_uuid=True).with_variant(
        sa.String(length=36), "sqlite"
    )


def upgrade() -> None:
    op.create_table(
        "session_guides",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("session_id", _uuid_type(), nullable=True),
        sa.Column("user_id", _uuid_type(), nullable=False),
        sa.Column("helper_id", _uuid_type(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("steps_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "steps_count >= 0",
            name="ck_session_guides_steps_count_non_negative",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["helper_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_session_guides_user_id", "session_guides", ["user_id"])
    op.create_index("ix_session_guides_session_id", "session_guides", ["session_id"])

    op.create_table(
        "guide_steps",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("guide_id", _uuid_type(), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "step_number >= 1",
            name="ck_guide_steps_step_number_positive",
        ),
        sa.ForeignKeyConstraint(["guide_id"], ["session_guides.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guide_steps_guide_id_step",
        "guide_steps",
        ["guide_id", "step_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_guide_steps_guide_id_step", table_name="guide_steps")
    op.drop_table("guide_steps")
    op.drop_index("ix_session_guides_session_id", table_name="session_guides")
    op.drop_index("ix_session_guides_user_id", table_name="session_guides")
    op.drop_table("session_guides")

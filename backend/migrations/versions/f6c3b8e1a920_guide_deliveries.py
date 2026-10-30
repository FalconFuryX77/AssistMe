"""Encrypted post-session guide deliveries.

Revision ID: f6c3b8e1a920
Revises: e5b7a2d91c40
Create Date: 2026-10-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f6c3b8e1a920"
down_revision: Union[str, None] = "e5b7a2d91c40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type() -> sa.types.TypeEngine:
    return sa.Uuid(as_uuid=False, native_uuid=True).with_variant(
        sa.String(length=36), "sqlite"
    )


def upgrade() -> None:
    op.create_table(
        "guide_deliveries",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("session_id", _uuid_type(), nullable=False),
        sa.Column("sender_id", _uuid_type(), nullable=False),
        sa.Column("recipient_id", _uuid_type(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_guide_deliveries_recipient_id", "guide_deliveries", ["recipient_id"])
    op.create_index("ix_guide_deliveries_session_id", "guide_deliveries", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_guide_deliveries_session_id", table_name="guide_deliveries")
    op.drop_index("ix_guide_deliveries_recipient_id", table_name="guide_deliveries")
    op.drop_table("guide_deliveries")

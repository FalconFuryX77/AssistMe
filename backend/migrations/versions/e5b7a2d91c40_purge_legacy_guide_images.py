"""Purge previously uploaded guide screenshots.

Revision ID: e5b7a2d91c40
Revises: d4f0a8c6b219
Create Date: 2026-10-26
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e5b7a2d91c40"
down_revision: Union[str, None] = "d4f0a8c6b219"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Older app versions uploaded screenshots as data URIs and retained them in
    # the database. The on-device guide flow no longer uses server-side images.
    op.execute("UPDATE guide_steps SET image_url = NULL WHERE image_url IS NOT NULL")


def downgrade() -> None:
    # This privacy cleanup is intentionally irreversible; cleared image data
    # cannot be reconstructed from the database.
    pass

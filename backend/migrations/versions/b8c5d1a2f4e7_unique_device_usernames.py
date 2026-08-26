"""Make device-first display names unique usernames.

Revision ID: b8c5d1a2f4e7
Revises: 432d7ff1e955
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b8c5d1a2f4e7"
down_revision: Union[str, None] = "432d7ff1e955"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Preserve existing accounts while making duplicate legacy names visibly
    # distinct. New accounts are rejected at the service layer before this
    # database constraint is reached.
    op.execute(
        """
        UPDATE users AS u
        SET display_name = u.display_name || ' · ' || substr(u.id, 1, 6)
        WHERE u.display_name IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM users AS earlier_user
              WHERE earlier_user.id < u.id
                AND lower(earlier_user.display_name) = lower(u.display_name)
          )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_users_display_name_ci
        ON users (lower(display_name))
        WHERE display_name IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_display_name_ci")

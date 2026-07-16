"""remove redundant single-column indexes

Revision ID: 8f1b2c3d4e5a
Revises: 79ea86508f64
Create Date: 2026-07-16 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "8f1b2c3d4e5a"
down_revision: Union[str, Sequence[str], None] = "79ea86508f64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


REDUNDANT_INDEXES = (
    ("active_sessions", "ix_active_sessions_expires_at", "expires_at"),
    ("password_reset_tokens", "ix_password_reset_tokens_expires_at", "expires_at"),
    ("test_case_sets", "ix_test_case_sets_team_id", "team_id"),
    ("user_team_permissions", "ix_user_team_permissions_permission", "permission"),
    ("user_team_permissions", "ix_user_team_permissions_team_id", "team_id"),
    ("user_team_permissions", "ix_user_team_permissions_user_id", "user_id"),
)


def upgrade() -> None:
    for table_name, index_name, _column_name in REDUNDANT_INDEXES:
        op.drop_index(index_name, table_name=table_name)


def downgrade() -> None:
    for table_name, index_name, column_name in REDUNDANT_INDEXES:
        op.create_index(index_name, table_name, [column_name], unique=False)

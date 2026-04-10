"""add_sessions_team_created_index

Revision ID: c3e5a7d9f1b2
Revises: b2a4f6c8d0e1
Create Date: 2026-04-10 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c3e5a7d9f1b2"
down_revision: Union[str, Sequence[str], None] = "b2a4f6c8d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_qa_ai_helper_sessions_team_created",
        "qa_ai_helper_sessions",
        ["team_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_qa_ai_helper_sessions_team_created",
        table_name="qa_ai_helper_sessions",
    )

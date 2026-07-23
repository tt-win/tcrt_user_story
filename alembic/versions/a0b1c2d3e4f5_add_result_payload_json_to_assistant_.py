"""add result_payload_json to assistant_tool_executions

Support persisting per-action tool result payloads in the journal so
batch_execute_actions can resume from partial execution safely.

Revision ID: a0b1c2d3e4f5
Revises: f9a1b2c3d4e5
Create Date: 2026-07-23 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db_types import medium_text_type


revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "f9a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assistant_tool_executions",
        sa.Column("result_payload_json", medium_text_type(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assistant_tool_executions", "result_payload_json")

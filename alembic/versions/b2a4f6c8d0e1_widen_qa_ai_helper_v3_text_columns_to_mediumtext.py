"""widen_qa_ai_helper_v3_text_columns_to_mediumtext

Revision ID: b2a4f6c8d0e1
Revises: 9c7d1e2f4a80
Create Date: 2026-04-02 21:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "b2a4f6c8d0e1"
down_revision: Union[str, Sequence[str], None] = "9c7d1e2f4a80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


QA_AI_HELPER_V3_TEXT_COLUMNS = (
    ("qa_ai_helper_check_conditions", "condition_text", False),
    ("qa_ai_helper_plan_sections", "section_title", False),
    ("qa_ai_helper_seed_items", "seed_summary", False),
    ("qa_ai_helper_seed_items", "comment_text", True),
    ("qa_ai_helper_verification_items", "summary", False),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return

    for table_name, column_name, nullable in QA_AI_HELPER_V3_TEXT_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Text(),
            type_=mysql.MEDIUMTEXT(),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return

    for table_name, column_name, nullable in QA_AI_HELPER_V3_TEXT_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=mysql.MEDIUMTEXT(),
            type_=sa.Text(),
            existing_nullable=nullable,
        )

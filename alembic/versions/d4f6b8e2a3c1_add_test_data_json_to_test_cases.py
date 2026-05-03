"""add_test_data_json_to_test_cases

Revision ID: d4f6b8e2a3c1
Revises: c3e5a7d9f1b2
Create Date: 2026-04-22 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db_types import MediumText


# revision identifiers, used by Alembic.
revision: str = "d4f6b8e2a3c1"
down_revision: Union[str, Sequence[str], None] = "c3e5a7d9f1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("test_cases")]
    if "test_data_json" not in columns:
        op.add_column(
            "test_cases",
            sa.Column("test_data_json", MediumText(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("test_cases")]
    if "test_data_json" in columns:
        op.drop_column("test_cases", "test_data_json")

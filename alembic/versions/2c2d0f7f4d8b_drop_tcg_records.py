"""drop_tcg_records

Revision ID: 2c2d0f7f4d8b
Revises: 7a26d2522198
Create Date: 2026-03-12 17:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2c2d0f7f4d8b"
down_revision: Union[str, Sequence[str], None] = "7a26d2522198"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tcg_records" in inspector.get_table_names():
        op.drop_table("tcg_records")


def downgrade() -> None:
    op.create_table(
        "tcg_records",
        sa.Column("tcg_number", sa.String(length=50), nullable=False),
        sa.Column("record_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("tcg_number"),
    )
    with op.batch_alter_table("tcg_records", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_tcg_records_record_id"),
            ["record_id"],
            unique=False,
        )

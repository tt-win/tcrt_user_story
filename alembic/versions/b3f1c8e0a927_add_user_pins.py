"""add_user_pins

Revision ID: b3f1c8e0a927
Revises: a7c1e9b3d5f2
Create Date: 2026-07-01 17:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3f1c8e0a927"
down_revision: Union[str, Sequence[str], None] = "a7c1e9b3d5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_pins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "entity_type", "entity_id", name="uq_user_pin"),
    )
    with op.batch_alter_table("user_pins", schema=None) as batch_op:
        batch_op.create_index("ix_user_pins_user_id", ["user_id"], unique=False)
        batch_op.create_index("ix_user_pins_team_id", ["team_id"], unique=False)
        batch_op.create_index("ix_user_pins_user_team", ["user_id", "team_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_pins_user_team", table_name="user_pins")
    op.drop_index("ix_user_pins_team_id", table_name="user_pins")
    op.drop_index("ix_user_pins_user_id", table_name="user_pins")
    op.drop_table("user_pins")

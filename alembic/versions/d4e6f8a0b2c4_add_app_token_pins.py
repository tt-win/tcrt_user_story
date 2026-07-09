"""add_app_token_pins

Adds the `app_token_pins` table: a team-scoped, shared pin list writable by
any app token (or legacy machine credential) with access to that team —
distinct from the existing per-user `user_pins` table used by the human web
UI. Non-destructive: only creates a new table with indexes; existing tables
are not modified.

Revision ID: d4e6f8a0b2c4
Revises: a1b2c3d4e5f6
Create Date: 2026-07-09 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e6f8a0b2c4"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_token_pins" in set(inspector.get_table_names()):
        return

    op.create_table(
        "app_token_pins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_team_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("created_by_credential_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("owner_team_id", "entity_type", "entity_id", name="uq_app_token_pin"),
    )
    op.create_index("ix_app_token_pins_owner_team_id", "app_token_pins", ["owner_team_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_token_pins" not in set(inspector.get_table_names()):
        return
    op.drop_index("ix_app_token_pins_owner_team_id", table_name="app_token_pins")
    op.drop_table("app_token_pins")

"""add_system_settings_table

Adds a generic org-level, runtime-mutable key/value settings table
(`system_settings`). First consumer: the Automation Hub entry-visibility
toggle (key `automation_hub_entry_enabled`). Missing keys fall back to
feature-specific defaults in the accessor layer, so no data backfill is
needed — an absent row means "default", not "off".

Revision ID: f1a2b3c4d5e6
Revises: e7c3a9d1f2b4
Create Date: 2026-06-15 09:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db_types import medium_text_type


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e7c3a9d1f2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "system_settings" in set(inspector.get_table_names()):
        return
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=100), primary_key=True, nullable=False),
        sa.Column("value", medium_text_type(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "system_settings" in set(inspector.get_table_names()):
        op.drop_table("system_settings")

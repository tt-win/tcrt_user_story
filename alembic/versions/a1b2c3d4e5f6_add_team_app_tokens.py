"""add_team_app_tokens

Adds the `team_app_tokens` table for team-owned app token credentials that
replace MCP machine tokens as the formal external API authentication model.
Non-destructive: only creates a new table with indexes; existing tables are
not modified.

Revision ID: a1b2c3d4e5f6
Revises: c8a1d3e5f7b9
Create Date: 2026-07-08 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db_types import medium_text_type


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "c8a1d3e5f7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "team_app_tokens" in set(inspector.get_table_names()):
        return

    op.create_table(
        "team_app_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", medium_text_type(), nullable=True),
        sa.Column("owner_team_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "revoked", name="teamapptokenstatus"),
            nullable=False,
        ),
        sa.Column("scopes_json", medium_text_type(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.UniqueConstraint("token_hash", name="uq_team_app_tokens_token_hash"),
    )
    op.create_index("ix_team_app_tokens_owner_team_id", "team_app_tokens", ["owner_team_id"])
    op.create_index("ix_team_app_tokens_status", "team_app_tokens", ["status"])
    op.create_index("ix_team_app_tokens_expires_at", "team_app_tokens", ["expires_at"])
    op.create_index("ix_team_app_tokens_created_by_user_id", "team_app_tokens", ["created_by_user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "team_app_tokens" not in set(inspector.get_table_names()):
        return
    op.drop_index("ix_team_app_tokens_created_by_user_id", table_name="team_app_tokens")
    op.drop_index("ix_team_app_tokens_expires_at", table_name="team_app_tokens")
    op.drop_index("ix_team_app_tokens_status", table_name="team_app_tokens")
    op.drop_index("ix_team_app_tokens_owner_team_id", table_name="team_app_tokens")
    op.drop_table("team_app_tokens")
    sa.Enum(name="teamapptokenstatus").drop(bind, checkfirst=True)

"""add global AI assistant tables

Revision ID: c9d2e4f6a8b1
Revises: 8f1b2c3d4e5a
Create Date: 2026-07-20 12:00:00.000000
"""

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "c9d2e4f6a8b1"
down_revision: Union[str, Sequence[str], None] = "8f1b2c3d4e5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _medium_text() -> sa.types.TypeEngine:
    return sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def upgrade() -> None:
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_key", sa.String(length=32), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "team_id",
            sa.Integer(),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scope_type", sa.String(length=16), nullable=False, server_default="global"),
        sa.Column("source_team_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("active_turn_key", sa.String(length=64), nullable=True),
        sa.Column("turn_lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_turn_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "conversation_key", name="uq_assistant_conversations_conversation_key"
        ),
        sa.CheckConstraint(
            # team_id 不可出現在此 check：其 FK 帶 ON DELETE SET NULL，
            # MySQL 8.0.16+ 禁止同一欄位同時用於 check constraint 與有動作的 FK（錯誤 3823）。
            "(scope_type = 'global' AND source_team_id IS NULL) "
            "OR (scope_type = 'team' AND source_team_id IS NOT NULL)",
            name="ck_assistant_conversations_scope",
        ),
        sa.CheckConstraint(
            "message_count >= 0", name="ck_assistant_conversations_message_count"
        ),
        sa.CheckConstraint(
            "next_turn_seq >= 0", name="ck_assistant_conversations_next_turn_seq"
        ),
    )
    op.create_index(
        "ix_assistant_conversations_user_id", "assistant_conversations", ["user_id"]
    )
    op.create_index(
        "ix_assistant_conversations_team_id", "assistant_conversations", ["team_id"]
    )
    op.create_index(
        "ix_assistant_conversations_status", "assistant_conversations", ["status"]
    )
    op.create_index(
        "ix_assistant_conversations_user_updated",
        "assistant_conversations",
        ["user_id", "last_message_at"],
    )
    op.create_index(
        "ix_assistant_conversations_last_message_at",
        "assistant_conversations",
        ["last_message_at"],
    )

    op.create_table(
        "assistant_turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("assistant_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn_seq", sa.Integer(), nullable=False),
        sa.Column("turn_key", sa.String(length=64), nullable=False),
        sa.Column("client_message_id", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column(
            "cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "admission_released", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("next_event_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_message_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", _medium_text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("turn_key", name="uq_assistant_turns_turn_key"),
        sa.UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name="uq_assistant_turns_client_message_id",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "turn_seq",
            name="uq_assistant_turns_conversation_seq",
        ),
        sa.CheckConstraint("turn_seq >= 0", name="ck_assistant_turns_turn_seq"),
    )
    op.create_index(
        "ix_assistant_turns_conversation_id", "assistant_turns", ["conversation_id"]
    )
    op.create_index(
        "ix_assistant_turns_conversation_status",
        "assistant_turns",
        ["conversation_id", "status"],
    )

    op.create_table(
        "assistant_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "turn_id",
            sa.Integer(),
            sa.ForeignKey("assistant_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload_json", _medium_text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("turn_id", "seq", name="uq_assistant_events_turn_seq"),
    )
    op.create_index("ix_assistant_events_turn_id", "assistant_events", ["turn_id"])

    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "turn_id",
            sa.Integer(),
            sa.ForeignKey("assistant_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", _medium_text(), nullable=True),
        sa.Column("tool_calls_json", _medium_text(), nullable=True),
        sa.Column("llm_tool_call_id", sa.String(length=64), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("turn_id", "message_seq", name="uq_assistant_messages_turn_seq"),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'tool')",
            name="ck_assistant_messages_role",
        ),
        sa.CheckConstraint(
            "role != 'tool' OR (llm_tool_call_id IS NOT NULL AND tool_name IS NOT NULL)",
            name="ck_assistant_messages_tool_pair",
        ),
        sa.CheckConstraint(
            "tool_calls_json IS NULL OR llm_tool_call_id IS NOT NULL",
            name="ck_assistant_messages_call_id",
        ),
    )
    op.create_index("ix_assistant_messages_turn_id", "assistant_messages", ["turn_id"])

    op.create_table(
        "assistant_pending_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "turn_id",
            sa.Integer(),
            sa.ForeignKey("assistant_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("execution_key", sa.String(length=64), nullable=False),
        sa.Column("llm_tool_call_id", sa.String(length=64), nullable=False),
        sa.Column("provider_tool_call_id", sa.String(length=64), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("arguments_redacted_json", _medium_text(), nullable=False),
        sa.Column("execution_payload_json", _medium_text(), nullable=True),
        sa.Column(
            "execution_payload_encrypted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("confirmation_summary_json", _medium_text(), nullable=False),
        sa.Column("confirmation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("executing_started_at", sa.DateTime(), nullable=True),
        sa.Column("execution_deadline", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "execution_key", name="uq_assistant_pending_actions_execution_key"
        ),
    )
    op.create_index(
        "ix_assistant_pending_actions_turn_id", "assistant_pending_actions", ["turn_id"]
    )
    op.create_index(
        "ix_assistant_pending_actions_status", "assistant_pending_actions", ["status"]
    )
    op.create_index(
        "ix_assistant_pending_actions_turn_status",
        "assistant_pending_actions",
        ["turn_id", "status"],
    )
    op.create_index(
        "ix_assistant_pending_actions_status_expires",
        "assistant_pending_actions",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_assistant_pending_actions_status_execution_deadline",
        "assistant_pending_actions",
        ["status", "execution_deadline"],
    )

    op.create_table(
        "assistant_tool_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("assistant_conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_conversation_key", sa.String(length=32), nullable=False),
        sa.Column("source_conversation_id", sa.Integer(), nullable=False),
        sa.Column("source_turn_key", sa.String(length=64), nullable=False),
        sa.Column("execution_key", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("llm_tool_call_id", sa.String(length=64), nullable=False),
        sa.Column("provider_tool_call_id", sa.String(length=64), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("arguments_json", _medium_text(), nullable=True),
        sa.Column("target_summary", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="started"),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_message", _medium_text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "execution_key", name="uq_assistant_tool_executions_execution_key"
        ),
    )
    op.create_index(
        "ix_assistant_tool_executions_conversation_id",
        "assistant_tool_executions",
        ["conversation_id"],
    )
    op.create_index(
        "ix_assistant_tool_executions_source_conversation_key",
        "assistant_tool_executions",
        ["source_conversation_key"],
    )
    op.create_index(
        "ix_assistant_tool_executions_source_conversation_id",
        "assistant_tool_executions",
        ["source_conversation_id"],
    )
    op.create_index(
        "ix_assistant_tool_executions_user_id", "assistant_tool_executions", ["user_id"]
    )
    op.create_index(
        "ix_assistant_tool_executions_status_created",
        "assistant_tool_executions",
        ["status", "created_at"],
    )

    op.create_table(
        "assistant_uploaded_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "turn_id",
            sa.Integer(),
            sa.ForeignKey("assistant_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attachment_index", sa.Integer(), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("relative_path", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "turn_id", "attachment_index", name="uq_assistant_uploaded_files_slot"
        ),
    )
    op.create_index(
        "ix_assistant_uploaded_files_turn_id",
        "assistant_uploaded_files",
        ["turn_id"],
    )
    op.create_index(
        "ix_assistant_uploaded_files_expires_at",
        "assistant_uploaded_files",
        ["expires_at"],
    )

    op.create_table(
        "assistant_rate_limit_buckets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("bucket_started_at", sa.DateTime(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "bucket_started_at",
            name="uq_assistant_rate_limit_user_bucket",
        ),
        sa.CheckConstraint(
            "used_count >= 0", name="ck_assistant_rate_limit_used_count"
        ),
    )
    op.create_index(
        "ix_assistant_rate_limit_buckets_user_id",
        "assistant_rate_limit_buckets",
        ["user_id"],
    )
    op.create_index(
        "ix_assistant_rate_limit_expires_at",
        "assistant_rate_limit_buckets",
        ["expires_at"],
    )

    op.create_table(
        "assistant_runtime_counters",
        sa.Column("scope_key", sa.String(length=80), primary_key=True),
        sa.Column("active_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "active_count >= 0", name="ck_assistant_runtime_counter_active"
        ),
    )
    runtime_counters = sa.table(
        "assistant_runtime_counters",
        sa.column("scope_key", sa.String(length=80)),
        sa.column("active_count", sa.Integer()),
        sa.column("updated_at", sa.DateTime()),
    )
    op.bulk_insert(
        runtime_counters,
        [{"scope_key": "global", "active_count": 0, "updated_at": datetime.utcnow()}],
    )


def downgrade() -> None:
    op.drop_table("assistant_runtime_counters")
    op.drop_table("assistant_rate_limit_buckets")
    op.drop_table("assistant_uploaded_files")
    op.drop_table("assistant_tool_executions")
    op.drop_table("assistant_pending_actions")
    op.drop_table("assistant_messages")
    op.drop_table("assistant_events")
    op.drop_table("assistant_turns")
    op.drop_table("assistant_conversations")

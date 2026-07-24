"""add knowledge query logs table

Revision ID: 20260724_knowledge_query_logs
Revises: 77b4f439d2f6
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = "20260724_knowledge_query_logs"
down_revision: Union[str, Sequence[str], None] = "77b4f439d2f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 大型文字欄位與 model 端 `from ..db_types import MediumText as Text` 對齊：MySQL 上
# 直接建出 MEDIUMTEXT（避免 64KB TEXT 截斷並滿足 `verify_large_text_columns` gate），
# 其他方言維持一般 TEXT。為已存在 audit DB 補一條 catch-up migration 把這批欄位從
# TEXT 升級到 MEDIUMTEXT（見後續 sibling migration）。
_LARGE_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def upgrade() -> None:
    op.create_table(
        "knowledge_query_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        # timestamp 採 client-side default，migration 不寫 server_default，避免 alembic
        # compare_server_default 判 drift。
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("query_id", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("turn_key", sa.String(length=128), nullable=True),
        sa.Column("llm_tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("query_text", _LARGE_TEXT, nullable=True),
        sa.Column("primary_team_id", sa.Integer(), nullable=True),
        sa.Column("allowed_team_ids", _LARGE_TEXT, nullable=True),
        sa.Column("top_k", sa.Integer(), nullable=True),
        sa.Column("score_threshold", sa.Float(), nullable=True),
        sa.Column("fallback_recommended", sa.SmallInteger(), nullable=True),
        sa.Column("degrade_reason", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("process", _LARGE_TEXT, nullable=True),
        sa.Column("results_summary", _LARGE_TEXT, nullable=True),
        sa.Column("error", _LARGE_TEXT, nullable=True),
        sa.Column("schema_version", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
    )
    # 對應 model 上的 single-column 與 composite 索引
    op.create_index(
        "ix_knowledge_query_logs_timestamp", "knowledge_query_logs", ["timestamp"], unique=False
    )
    op.create_index(
        "ix_knowledge_query_logs_query_id", "knowledge_query_logs", ["query_id"], unique=False
    )
    op.create_index(
        "ix_knowledge_query_logs_source_timestamp",
        "knowledge_query_logs",
        ["source", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_query_logs_status_timestamp",
        "knowledge_query_logs",
        ["status", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_query_logs_primary_team_timestamp",
        "knowledge_query_logs",
        ["primary_team_id", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_query_logs_user_timestamp",
        "knowledge_query_logs",
        ["user_id", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_query_logs_user_timestamp", table_name="knowledge_query_logs")
    op.drop_index(
        "ix_knowledge_query_logs_primary_team_timestamp", table_name="knowledge_query_logs"
    )
    op.drop_index("ix_knowledge_query_logs_status_timestamp", table_name="knowledge_query_logs")
    op.drop_index("ix_knowledge_query_logs_source_timestamp", table_name="knowledge_query_logs")
    op.drop_index("ix_knowledge_query_logs_query_id", table_name="knowledge_query_logs")
    op.drop_index("ix_knowledge_query_logs_timestamp", table_name="knowledge_query_logs")
    op.drop_table("knowledge_query_logs")

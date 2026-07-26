"""add context_team_id to assistant_turns

全域對話（scope_type='global'）沒有綁定 team，但仍需要能執行 team-scoped 操作。
每個 turn 快照建立當下的工作區 team（前端提供、伺服器驗證），之後該 turn 與其
confirm continuation 的所有工具執行都以此快照為目標 team——確認卡出現後使用者切換
工作區也不會改變已建立動作的目標（見 spec assistant-conversations「turn 的 context
team 快照」）。

欄位 nullable、既有資料一律 NULL（等同「無 context team」→ 只提供 discovery 工具），
因此不需回填。FK ON DELETE SET NULL：team 被刪除時快照自動失效，fail-closed。

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-07-25 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table：SQLite 無法以裸 ALTER 加上具名 FK 約束，需重建表。
    with op.batch_alter_table("assistant_turns", schema=None) as batch_op:
        batch_op.add_column(sa.Column("context_team_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_assistant_turns_context_team_id",
            "teams",
            ["context_team_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_assistant_turns_context_team_id", ["context_team_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("assistant_turns", schema=None) as batch_op:
        batch_op.drop_index("ix_assistant_turns_context_team_id")
        batch_op.drop_constraint("fk_assistant_turns_context_team_id", type_="foreignkey")
        batch_op.drop_column("context_team_id")

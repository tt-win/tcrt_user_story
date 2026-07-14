"""enforce_case_insensitive_username_uniqueness

`users.username` 原本以 `unique=True`（單純唯一索引）保證唯一性。這在 SQLite／PostgreSQL
上是大小寫「敏感」的唯一性（'nikki' 與 'Nikki' 視為不同值），但 MySQL 的 VARCHAR 欄位預設
collation（`utf8mb4_0900_ai_ci` / `utf8mb4_general_ci`）本身就是大小寫不敏感，導致三引擎
實際唯一性語意不一致 —— 這正是 `scripts/db_cross_migrate.py` 過去需要
`_dedup_users_payload_case_insensitive` 在 SQLite→MySQL 搬遷當下即時去重的原因（SQLite
上允許並存的 'nikki'／'Nikki' 兩筆資料，搬到 MySQL 會撞唯一鍵）。

本遷移改以 `lower(username)` 建立 unique index，讓三引擎的唯一性語意一致（不再依賴 MySQL
特定 collation 的隱含行為），使 `db_cross_migrate.py` 不再需要對 username 唯一性的正確性
負責。SQLAlchemy 針對 `func.lower(...)` 索引欄位會依 dialect 自動產生正確語法：
MySQL 8.0.13+ 需要雙層括號的 functional key part 語法
`CREATE UNIQUE INDEX ... ON users ((lower(username)))`，SQLite／PostgreSQL 則是
`CREATE UNIQUE INDEX ... ON users (lower(username))`；已針對三引擎個別驗證。

若既有資料已存在僅大小寫不同的重複 username（在 SQLite／PostgreSQL 上目前的 schema
允許這種情況），本遷移不會自動嘗試合併或刪除任何一筆 —— 保留／刪除哪一筆是需要人判斷
的業務決策，貿然自動合併可能誤刪看似重複、實際上是不同使用者的帳號，且合併／刪除
使用者列這種操作本質上不可逆。因此遇到重複直接中止遷移（`RuntimeError`，列出所有衝突的
username 與對應 id），交由人工先行合併或改名。Change A 的開機備份／升級失敗回退機制會在
此情況下接手，不會讓資料庫卡在半遷移狀態、也不會有任何資料遺失。

Revision ID: f5f2d075fd93
Revises: 9cd6393a4da6
Create Date: 2026-07-14 09:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f5f2d075fd93"
down_revision: Union[str, Sequence[str], None] = "9cd6393a4da6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    users = sa.table("users", sa.column("id"), sa.column("username"))

    duplicate_groups = bind.execute(
        sa.text(
            "SELECT lower(username) AS uname_lower FROM users "
            "GROUP BY lower(username) HAVING COUNT(*) > 1"
        )
    ).fetchall()

    if duplicate_groups:
        details = []
        for row in duplicate_groups:
            matches = bind.execute(
                sa.select(users.c.id, users.c.username).where(
                    sa.func.lower(users.c.username) == row.uname_lower
                )
            ).fetchall()
            details.append(
                f"  {row.uname_lower!r}: " + ", ".join(f"id={m.id}({m.username!r})" for m in matches)
            )
        raise RuntimeError(
            "偵測到僅大小寫不同的重複 username，無法自動決定應保留哪一筆（合併／刪除使用者"
            "屬於需要人工判斷的業務決策）。請先手動合併或改名後再重新升級：\n"
            + "\n".join(details)
        )

    op.drop_index("ix_users_username", table_name="users")
    op.create_index(
        "uq_users_username_lower",
        "users",
        [sa.func.lower(sa.column("username"))],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_users_username_lower", table_name="users")
    op.create_index("ix_users_username", "users", ["username"], unique=True)

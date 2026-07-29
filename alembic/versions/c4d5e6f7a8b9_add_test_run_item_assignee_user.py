"""add local assignee identity to test run items

Revision ID: c4d5e6f7a8b9
Revises: b1c2d3e4f5a6
Create Date: 2026-07-28 10:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FK_NAME = "fk_test_run_items_assignee_user_id"
_ITEM_INDEX = "ix_test_run_items_assignee_user_updated"
_HISTORY_INDEX = "ix_result_history_changed_by_time"
_WRITE_ROLES = {"user", "admin", "super_admin"}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite needs a table rebuild to add a named FK constraint.
        with op.batch_alter_table("test_run_items", schema=None) as batch_op:
            batch_op.add_column(sa.Column("assignee_user_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                _FK_NAME,
                "users",
                ["assignee_user_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index(_ITEM_INDEX, ["assignee_user_id", "updated_at"], unique=False)
    else:
        op.add_column("test_run_items", sa.Column("assignee_user_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            _FK_NAME,
            "test_run_items",
            "users",
            ["assignee_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(_ITEM_INDEX, "test_run_items", ["assignee_user_id", "updated_at"], unique=False)

    op.create_index(
        _HISTORY_INDEX,
        "test_run_item_result_history",
        ["changed_by_id", "changed_at"],
        unique=False,
    )
    _backfill_exact_local_assignees(bind)


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index(_HISTORY_INDEX, table_name="test_run_item_result_history")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("test_run_items", schema=None) as batch_op:
            batch_op.drop_index(_ITEM_INDEX)
            batch_op.drop_constraint(_FK_NAME, type_="foreignkey")
            batch_op.drop_column("assignee_user_id")
    else:
        op.drop_index(_ITEM_INDEX, table_name="test_run_items")
        op.drop_constraint(_FK_NAME, "test_run_items", type_="foreignkey")
        op.drop_column("test_run_items", "assignee_user_id")


def _backfill_exact_local_assignees(bind) -> None:
    """Backfill only active, write-capable, uniquely identified users.

    This uses Python normalization rather than dialect-specific ``ILIKE`` or
    generated columns, keeping SQLite, MySQL and PostgreSQL semantics aligned.
    """

    users = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("lark_user_id", sa.String),
        sa.column("email", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("role", sa.String),
    )
    items = sa.table(
        "test_run_items",
        sa.column("id", sa.Integer),
        sa.column("assignee_id", sa.String),
        sa.column("assignee_email", sa.String),
        sa.column("assignee_user_id", sa.Integer),
    )

    lark_candidates: dict[str, list[int]] = {}
    email_candidates: dict[str, list[int]] = {}
    for row in bind.execute(sa.select(users)).mappings():
        role = str(row["role"] or "").strip().lower()
        if not row["is_active"] or role not in _WRITE_ROLES:
            continue
        user_id = int(row["id"])
        lark_id = _trim_to_none(row["lark_user_id"])
        email = _normalized_email(row["email"])
        if lark_id:
            lark_candidates.setdefault(lark_id, []).append(user_id)
        if email:
            email_candidates.setdefault(email, []).append(user_id)

    for row in bind.execute(
        sa.select(items.c.id, items.c.assignee_id, items.c.assignee_email).where(
            items.c.assignee_user_id.is_(None)
        )
    ).mappings():
        lark_id = _trim_to_none(row["assignee_id"])
        email = _normalized_email(row["assignee_email"])
        lark_matches = lark_candidates.get(lark_id, []) if lark_id else []
        email_matches = email_candidates.get(email, []) if email else []

        candidate_id = None
        if lark_id and email:
            if len(lark_matches) == 1 and len(email_matches) == 1 and lark_matches[0] == email_matches[0]:
                candidate_id = lark_matches[0]
        elif lark_id and len(lark_matches) == 1:
            candidate_id = lark_matches[0]
        elif email and len(email_matches) == 1:
            candidate_id = email_matches[0]

        if candidate_id is not None:
            bind.execute(
                sa.update(items)
                .where(items.c.id == row["id"])
                .values(assignee_user_id=candidate_id)
            )


def _trim_to_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized_email(value: object) -> str | None:
    text = _trim_to_none(value)
    return text.lower() if text else None

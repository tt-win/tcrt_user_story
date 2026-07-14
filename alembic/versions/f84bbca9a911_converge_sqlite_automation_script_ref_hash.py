"""converge_sqlite_automation_script_ref_hash

`e7c3a9d1f2b4` intentionally left SQLite's `automation_scripts` schema unchanged
(still the original 5-column `uq_automation_script_ref` constraint) since every
SQLite deployment had already applied that exact DDL; only MySQL/PostgreSQL got the
new `ref_key_hash`-based scheme there (never having successfully run that migration
before). But `app/models/database_models.py`'s `AutomationScript` ORM class declares
`ref_key_hash` unconditionally for all engines — so any SQLite database that only
went through the old `e7c3a9d1f2b4` path is missing a column the ORM now always
inserts into. This migration converges SQLite onto the same `ref_key_hash` scheme,
scoped to SQLite only: MySQL/PostgreSQL already have it from `e7c3a9d1f2b4` and this
is a no-op for them.

Revision ID: f84bbca9a911
Revises: a371471a3008
Create Date: 2026-07-14 12:30:00.000000
"""

import hashlib
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f84bbca9a911"
down_revision: Union[str, Sequence[str], None] = "a371471a3008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ref_key_hash(team_id: int, provider_id: int, ref_repo: str, ref_path: str, ref_branch: str) -> str:
    """Must match app.models.database_models._automation_script_ref_key_hash exactly."""
    parts = "\x1f".join([str(team_id), str(provider_id), ref_repo, ref_path, ref_branch])
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return

    inspector = sa.inspect(bind)
    if "automation_scripts" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("automation_scripts")}
    if "ref_key_hash" in columns:
        return

    with op.batch_alter_table("automation_scripts") as batch_op:
        batch_op.add_column(sa.Column("ref_key_hash", sa.String(length=64), nullable=True))

    rows = bind.execute(
        sa.text("SELECT id, team_id, provider_id, ref_repo, ref_path, ref_branch FROM automation_scripts")
    ).mappings().all()
    for row in rows:
        digest = _ref_key_hash(
            row["team_id"], row["provider_id"], row["ref_repo"], row["ref_path"], row["ref_branch"]
        )
        bind.execute(
            sa.text("UPDATE automation_scripts SET ref_key_hash = :digest WHERE id = :id"),
            {"digest": digest, "id": row["id"]},
        )

    with op.batch_alter_table("automation_scripts") as batch_op:
        batch_op.alter_column("ref_key_hash", existing_type=sa.String(length=64), nullable=False)
        batch_op.drop_constraint("uq_automation_script_ref", type_="unique")
        batch_op.create_unique_constraint("uq_automation_script_ref", ["ref_key_hash"])
        batch_op.create_index(
            "ix_automation_scripts_team_provider_repo_branch",
            ["team_id", "provider_id", "ref_repo", "ref_branch"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return

    inspector = sa.inspect(bind)
    if "automation_scripts" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("automation_scripts")}
    if "ref_key_hash" not in columns:
        return

    with op.batch_alter_table("automation_scripts") as batch_op:
        batch_op.drop_index("ix_automation_scripts_team_provider_repo_branch")
        batch_op.drop_constraint("uq_automation_script_ref", type_="unique")
        batch_op.create_unique_constraint(
            "uq_automation_script_ref",
            ["team_id", "provider_id", "ref_repo", "ref_path", "ref_branch"],
        )
        batch_op.drop_column("ref_key_hash")

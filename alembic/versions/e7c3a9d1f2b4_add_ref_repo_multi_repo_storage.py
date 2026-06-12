"""add_ref_repo_for_multi_repo_storage

Adds a `ref_repo` ("owner/repo") discriminator so a single GitHub storage
provider config can hold multiple repos:

- `automation_scripts.ref_repo` — which repo a cached script came from. The
  uniqueness key gains `ref_repo` so two repos can share the same `ref_path`
  (e.g. both have `tests/test_login.py`).
- `automation_script_groups.ref_repo` — the single repo a suite is bound to
  (suites stay single-repo; see B1).

Backfill: existing rows are populated from their storage provider's
`config_json` (legacy flat `owner`/`repo`, or `repos[0]` if already migrated).
Non-derivable rows keep the "" sentinel.

Revision ID: e7c3a9d1f2b4
Revises: d5e6f7a8b9c0
Create Date: 2026-06-10 09:00:00.000000
"""

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7c3a9d1f2b4"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slug_from_config(config_json: str | None) -> str:
    """Derive an `owner/repo` slug from a storage provider's config_json."""
    if not config_json:
        return ""
    try:
        cfg = json.loads(config_json)
    except (TypeError, ValueError):
        return ""
    if not isinstance(cfg, dict):
        return ""
    repos = cfg.get("repos")
    if isinstance(repos, list) and repos:
        first = repos[0]
        if isinstance(first, dict) and first.get("owner") and first.get("repo"):
            return f"{first['owner']}/{first['repo']}"
    owner = cfg.get("owner")
    repo = cfg.get("repo")
    if owner and repo:
        return f"{owner}/{repo}"
    return ""


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "automation_scripts" in tables:
        columns = {c["name"] for c in inspector.get_columns("automation_scripts")}
        if "ref_repo" not in columns:
            with op.batch_alter_table("automation_scripts") as batch_op:
                batch_op.add_column(
                    sa.Column("ref_repo", sa.String(length=255), nullable=False, server_default="")
                )
                batch_op.drop_constraint("uq_automation_script_ref", type_="unique")
                batch_op.create_unique_constraint(
                    "uq_automation_script_ref",
                    ["team_id", "provider_id", "ref_repo", "ref_path", "ref_branch"],
                )

    if "automation_script_groups" in tables:
        columns = {c["name"] for c in inspector.get_columns("automation_script_groups")}
        if "ref_repo" not in columns:
            with op.batch_alter_table("automation_script_groups") as batch_op:
                batch_op.add_column(
                    sa.Column("ref_repo", sa.String(length=255), nullable=False, server_default="")
                )

    # Backfill from each row's storage provider config_json.
    if "automation_scripts" in tables and "team_automation_providers" in tables:
        script_rows = bind.execute(
            sa.text(
                "SELECT s.id AS id, p.config_json AS config_json "
                "FROM automation_scripts s "
                "JOIN team_automation_providers p ON s.provider_id = p.id"
            )
        ).mappings().all()
        for row in script_rows:
            slug = _slug_from_config(row["config_json"])
            if slug:
                bind.execute(
                    sa.text("UPDATE automation_scripts SET ref_repo = :slug WHERE id = :id"),
                    {"slug": slug, "id": row["id"]},
                )

    if "automation_script_groups" in tables and "team_automation_providers" in tables:
        group_rows = bind.execute(
            sa.text("SELECT id, team_id FROM automation_script_groups")
        ).mappings().all()
        for row in group_rows:
            config_json = bind.execute(
                sa.text(
                    "SELECT config_json FROM team_automation_providers "
                    "WHERE team_id = :tid AND provider_slot = 'storage' "
                    "ORDER BY is_active DESC, updated_at DESC LIMIT 1"
                ),
                {"tid": row["team_id"]},
            ).scalar()
            slug = _slug_from_config(config_json)
            if slug:
                bind.execute(
                    sa.text("UPDATE automation_script_groups SET ref_repo = :slug WHERE id = :id"),
                    {"slug": slug, "id": row["id"]},
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "automation_scripts" in tables:
        columns = {c["name"] for c in inspector.get_columns("automation_scripts")}
        if "ref_repo" in columns:
            with op.batch_alter_table("automation_scripts") as batch_op:
                batch_op.drop_constraint("uq_automation_script_ref", type_="unique")
                batch_op.create_unique_constraint(
                    "uq_automation_script_ref",
                    ["team_id", "provider_id", "ref_path", "ref_branch"],
                )
                batch_op.drop_column("ref_repo")

    if "automation_script_groups" in tables:
        columns = {c["name"] for c in inspector.get_columns("automation_script_groups")}
        if "ref_repo" in columns:
            with op.batch_alter_table("automation_script_groups") as batch_op:
                batch_op.drop_column("ref_repo")

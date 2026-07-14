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

**2026-07-14 engine-portability fix**: `uq_automation_script_ref` widening to 5
columns (`team_id, provider_id, ref_repo(255), ref_path(500), ref_branch(200)`)
exceeds MySQL's 3072-byte max index key length under utf8mb4 (955 chars * 4
bytes/char alone, before the two integer columns), so this revision could never
complete on a real MySQL server. Since this revision has never successfully run
against MySQL or PostgreSQL in any real deployment, there is no existing behavior
to preserve for those two dialects there (unlike SQLite, where every deployment
has already applied the 5-column constraint exactly as before — kept unchanged
below). For MySQL/PostgreSQL, uniqueness is instead carried by a fixed-length
`ref_key_hash` column (SHA-256 of the 5 logical key parts, computed in
`app.models.database_models._automation_script_ref_key_hash` and kept in sync by
a `before_insert` ORM event listener since these 5 columns are immutable after
creation), with a plain supporting index on `(team_id, provider_id, ref_repo,
ref_branch)` for the bulk per-repo/branch lookup in
`app/services/automation/script_service.py`. A later migration converges
already-migrated SQLite databases (which still have the 5-column constraint) to
the same `ref_key_hash` scheme.

Revision ID: e7c3a9d1f2b4
Revises: d5e6f7a8b9c0
Create Date: 2026-06-10 09:00:00.000000
"""

import hashlib
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


def _ref_key_hash(team_id: int, provider_id: int, ref_repo: str, ref_path: str, ref_branch: str) -> str:
    """Must match app.models.database_models._automation_script_ref_key_hash exactly."""
    parts = "\x1f".join([str(team_id), str(provider_id), ref_repo, ref_path, ref_branch])
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    is_sqlite = bind.dialect.name == "sqlite"

    if "automation_scripts" in tables:
        columns = {c["name"] for c in inspector.get_columns("automation_scripts")}
        if "ref_repo" not in columns:
            with op.batch_alter_table("automation_scripts") as batch_op:
                batch_op.add_column(
                    sa.Column("ref_repo", sa.String(length=255), nullable=False, server_default="")
                )
                if is_sqlite:
                    # Unchanged since first shipped: every SQLite deployment has
                    # already applied this exact 5-column constraint.
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

    # MySQL/PostgreSQL only: carry uniqueness via a fixed-length hash column
    # instead of the over-long 5-column composite (see module docstring).
    if not is_sqlite and "automation_scripts" in tables:
        columns = {c["name"] for c in inspector.get_columns("automation_scripts")}
        if "ref_key_hash" not in columns:
            op.add_column("automation_scripts", sa.Column("ref_key_hash", sa.String(length=64), nullable=True))
            rows = bind.execute(
                sa.text(
                    "SELECT id, team_id, provider_id, ref_repo, ref_path, ref_branch FROM automation_scripts"
                )
            ).mappings().all()
            for row in rows:
                digest = _ref_key_hash(
                    row["team_id"], row["provider_id"], row["ref_repo"], row["ref_path"], row["ref_branch"]
                )
                bind.execute(
                    sa.text("UPDATE automation_scripts SET ref_key_hash = :digest WHERE id = :id"),
                    {"digest": digest, "id": row["id"]},
                )
            op.alter_column("automation_scripts", "ref_key_hash", existing_type=sa.String(length=64), nullable=False)
            # Drop the 4-column constraint from 7a26d2522198 (still present here: it
            # predates ref_repo and fits under MySQL's key-length limit on its own,
            # so it succeeded when the initial schema first ran) before reusing its
            # name for the new hash-based constraint.
            op.drop_constraint("uq_automation_script_ref", "automation_scripts", type_="unique")
            op.create_unique_constraint(
                "uq_automation_script_ref", "automation_scripts", ["ref_key_hash"]
            )
            op.create_index(
                "ix_automation_scripts_team_provider_repo_branch",
                "automation_scripts",
                ["team_id", "provider_id", "ref_repo", "ref_branch"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    is_sqlite = bind.dialect.name == "sqlite"

    if "automation_scripts" in tables:
        columns = {c["name"] for c in inspector.get_columns("automation_scripts")}
        if "ref_repo" in columns:
            if is_sqlite:
                with op.batch_alter_table("automation_scripts") as batch_op:
                    batch_op.drop_constraint("uq_automation_script_ref", type_="unique")
                    batch_op.create_unique_constraint(
                        "uq_automation_script_ref",
                        ["team_id", "provider_id", "ref_path", "ref_branch"],
                    )
                    batch_op.drop_column("ref_repo")
            else:
                if "ref_key_hash" in columns:
                    op.drop_index("ix_automation_scripts_team_provider_repo_branch", table_name="automation_scripts")
                    op.drop_constraint("uq_automation_script_ref", "automation_scripts", type_="unique")
                    op.drop_column("automation_scripts", "ref_key_hash")
                op.create_unique_constraint(
                    "uq_automation_script_ref",
                    "automation_scripts",
                    ["team_id", "provider_id", "ref_path", "ref_branch"],
                )
                op.drop_column("automation_scripts", "ref_repo")

    if "automation_script_groups" in tables:
        columns = {c["name"] for c in inspector.get_columns("automation_script_groups")}
        if "ref_repo" in columns:
            with op.batch_alter_table("automation_script_groups") as batch_op:
                batch_op.drop_column("ref_repo")

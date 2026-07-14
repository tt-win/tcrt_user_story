"""widen_remaining_text_columns_to_mediumtext

Catch-up for `8d3c1b4a6f20`: several tables/columns were added by later migrations
using plain `sa.Text()` instead of the portable `MediumText` type alias, so they were
never promoted to MEDIUMTEXT on MySQL. This was only discoverable once a fresh MySQL
bootstrap could actually reach `database_init.py`'s `verify_large_text_columns()` gate
— which the pre-existing engine-portability bugs fixed in `b9d4e7a3c0f2`/
`e7c3a9d1f2b4`/`c3e7a1f9d2b4` blocked entirely until now. `Text` is aliased to
`MediumText` throughout `app/models/database_models.py`, so every one of these columns
is model-intended to be MEDIUMTEXT.

Unlike `8d3c1b4a6f20` (a generic "any Text-affinity column" scan — safe there because
nothing was MEDIUMTEXT yet), this migration hardcodes the exact column list: several
widen migrations have already run by this point (`8d3c1b4a6f20` itself, plus the two
qa_ai_helper-specific ones), so a generic scan's `downgrade()` would incorrectly demote
*their* already-MEDIUMTEXT columns back to TEXT too, not just the ones this migration
promotes.

Revision ID: a371471a3008
Revises: f5f2d075fd93
Create Date: 2026-07-14 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "a371471a3008"
down_revision: Union[str, Sequence[str], None] = "f5f2d075fd93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table_name, column_name, nullable)
_COLUMNS = [
    ("test_run_sets", "automation_suite_ids_json", True),
    ("qa_ai_helper_prompt_profiles", "description", True),
    ("system_automation_providers", "config_json", False),
    ("system_automation_providers", "credentials_encrypted", True),
    ("automation_scripts", "declared_vars_json", True),
    ("automation_environments", "description", True),
    ("automation_environment_params", "value_plaintext", True),
    ("automation_environment_params", "value_encrypted", True),
    ("automation_script_env_vars", "value_plaintext", True),
    ("automation_script_env_vars", "value_encrypted", True),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table_name, column_name, nullable in _COLUMNS:
        if table_name not in existing_tables:
            continue
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Text(),
            type_=mysql.MEDIUMTEXT(),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table_name, column_name, nullable in _COLUMNS:
        if table_name not in existing_tables:
            continue
        op.alter_column(
            table_name,
            column_name,
            existing_type=mysql.MEDIUMTEXT(),
            type_=sa.Text(),
            existing_nullable=nullable,
        )

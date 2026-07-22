"""widen assistant_skills TEXT columns to MEDIUMTEXT on MySQL

Catch-up for e8f1a2b3c4d5: ``description`` and ``triggers_json`` were created with
plain ``sa.Text()`` (MySQL TEXT) while the ORM declares them as portable MediumText
(``Text`` is aliased to MediumText in database_models). Bootstrap
``verify_large_text_columns`` then fails and aborts server start.

Revision ID: f9a1b2c3d4e5
Revises: e8f1a2b3c4d5
Create Date: 2026-07-22 20:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "f9a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e8f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, nullable)
_COLUMNS = [
    ("assistant_skills", "description", False),
    ("assistant_skills", "triggers_json", True),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return

    inspector = sa.inspect(bind)
    if "assistant_skills" not in set(inspector.get_table_names()):
        return

    actual = {c["name"]: c for c in inspector.get_columns("assistant_skills")}
    for table_name, column_name, nullable in _COLUMNS:
        col = actual.get(column_name)
        if col is None:
            continue
        type_name = getattr(col["type"].__class__, "__name__", "").upper()
        if type_name in {"MEDIUMTEXT", "LONGTEXT"}:
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
    if "assistant_skills" not in set(inspector.get_table_names()):
        return

    for table_name, column_name, nullable in _COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=mysql.MEDIUMTEXT(),
            type_=sa.Text(),
            existing_nullable=nullable,
        )

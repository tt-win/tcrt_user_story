"""widen_main_text_columns_to_mediumtext

Revision ID: 8d3c1b4a6f20
Revises: 4b5d8f2c1a9e
Create Date: 2026-03-31 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.sql import sqltypes


revision: str = "8d3c1b4a6f20"
down_revision: Union[str, Sequence[str], None] = "4b5d8f2c1a9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _should_promote(column_type: sa.types.TypeEngine) -> bool:
    type_name = column_type.__class__.__name__.upper()
    if type_name in {"MEDIUMTEXT", "LONGTEXT"}:
        return False
    return isinstance(column_type, sqltypes.Text)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return

    inspector = sa.inspect(bind)
    for table_name in inspector.get_table_names():
        if table_name == "alembic_version":
            continue
        for column in inspector.get_columns(table_name):
            if not _should_promote(column["type"]):
                continue
            op.alter_column(
                table_name,
                column["name"],
                existing_type=column["type"],
                type_=mysql.MEDIUMTEXT(),
                existing_nullable=bool(column["nullable"]),
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return

    inspector = sa.inspect(bind)
    for table_name in inspector.get_table_names():
        if table_name == "alembic_version":
            continue
        for column in inspector.get_columns(table_name):
            type_name = column["type"].__class__.__name__.upper()
            if type_name not in {"MEDIUMTEXT", "LONGTEXT"}:
                continue
            op.alter_column(
                table_name,
                column["name"],
                existing_type=column["type"],
                type_=sa.Text(),
                existing_nullable=bool(column["nullable"]),
            )

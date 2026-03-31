"""widen_usm_text_columns_to_mediumtext

Revision ID: 7bc2e5a91d44
Revises: 5c56712a0014
Create Date: 2026-03-31 12:02:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.sql import sqltypes


revision: str = "7bc2e5a91d44"
down_revision: Union[str, Sequence[str], None] = "5c56712a0014"
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

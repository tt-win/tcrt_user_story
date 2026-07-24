"""widen_knowledge_query_logs_text_columns_to_mediumtext

Catch-up for ``20260724_knowledge_query_logs``: the original create_table used
plain ``sa.Text()`` for the five large-text columns (``query_text``,
``allowed_team_ids``, ``process``, ``results_summary``, ``error``), so MySQL
databases that already ran that revision end up with physical ``TEXT`` columns
(64KB cap, truncates large RAG query payloads and process diagnostics). Model
side ``app/audit/database.py`` declares these as ``Text`` aliased to
``MediumText`` (``from ..db_types import MediumText as Text``), and
``database_init.py``'s ``verify_large_text_columns`` gate refuses to start the
server until they are physically ``MEDIUMTEXT``/``LONGTEXT`` on MySQL.

This migration hardcodes the exact column list (mirroring the
``a371471a3008_widen_remaining_text_columns_to_mediumtext`` pattern from the
main branch): several audit widen migrations have already run by this point
(``8ac7d1e42b90``), so a generic "any Text-affinity column" scan would also
re-promote their already-MEDIUMTEXT columns in some paths and is therefore
unsafe here. We instead only touch the five knowledge_query_logs columns that
this change's original migration missed.

The same revision in the source change is also amended to declare these
columns via ``sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")`` so that
fresh MySQL databases create the table with ``MEDIUMTEXT`` from the start and
do not need this catch-up step.

Downgrade note (mirroring the established TCRT catch-up migration convention
in ``a371471a3008`` / ``8ac7d1e42b90`` / ``8d3c1b4a6f20``): downgrade reverts
the columns back to ``TEXT``. This is safe only if the rows fit within MySQL's
64KB TEXT cap; on a system with strict SQL mode the downgrade transaction will
fail with ``Data too long for column`` if any of ``query_text`` /
``allowed_team_ids`` / ``process`` / ``results_summary`` / ``error`` rows
already exceed 64KB. Operators should consider this a one-way migration
unless they have pruned oversized rows beforehand.

Revision ID: b1c2d3e4f506
Revises: 20260724_knowledge_query_logs
Create Date: 2026-07-24 19:55:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "b1c2d3e4f506"
down_revision: Union[str, Sequence[str], None] = "20260724_knowledge_query_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table_name, column_name, nullable)
_COLUMNS = [
    ("knowledge_query_logs", "query_text", True),
    ("knowledge_query_logs", "allowed_team_ids", True),
    ("knowledge_query_logs", "process", True),
    ("knowledge_query_logs", "results_summary", True),
    ("knowledge_query_logs", "error", True),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return

    for table_name, column_name, nullable in _COLUMNS:
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

    for table_name, column_name, nullable in _COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=mysql.MEDIUMTEXT(),
            type_=sa.Text(),
            existing_nullable=nullable,
        )

"""move assistant team target from page-context turns to pending actions

Revision ID: f0c1e2d3a4b5
Revises: c4d5e6f7a8b9
Create Date: 2026-07-31 10:00:00.000000
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db_types import medium_text_type


revision: str = "f0c1e2d3a4b5"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OPEN_STATUSES = {"pending", "executing"}


def _summary_target(raw: str | None) -> tuple[int, str] | None:
    try:
        summary = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    team_id = summary.get("team_id") if isinstance(summary, dict) else None
    team_name = summary.get("team_name") if isinstance(summary, dict) else None
    if not isinstance(team_id, int) or isinstance(team_id, bool) or team_id <= 0:
        return None
    if not isinstance(team_name, str) or not team_name.strip():
        return None
    return team_id, team_name.strip()


def upgrade() -> None:
    with op.batch_alter_table("assistant_pending_actions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("target_team_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("target_team_name_snapshot", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("target_selector_json", medium_text_type(), nullable=True))
        batch_op.create_index(
            "ix_assistant_pending_actions_target_team_id", ["target_team_id"], unique=False
        )
    op.add_column(
        "assistant_tool_executions",
        sa.Column("target_selector_json", medium_text_type(), nullable=True),
    )

    connection = op.get_bind()
    pending = sa.table(
        "assistant_pending_actions",
        sa.column("id", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("confirmation_summary_json", sa.Text()),
        sa.column("execution_payload_json", sa.Text()),
        sa.column("execution_payload_encrypted", sa.Boolean()),
        sa.column("resolved_at", sa.DateTime()),
        sa.column("target_team_id", sa.Integer()),
        sa.column("target_team_name_snapshot", sa.String()),
        sa.column("target_selector_json", sa.Text()),
    )
    rows = connection.execute(
        sa.select(
            pending.c.id,
            pending.c.status,
            pending.c.confirmation_summary_json,
            pending.c.execution_payload_json,
            pending.c.execution_payload_encrypted,
        )
    ).all()
    now = datetime.utcnow()
    for row in rows:
        target = _summary_target(row.confirmation_summary_json)
        values: dict[str, object] = {}
        if target is not None:
            team_id, team_name = target
            values.update(
                target_team_id=team_id,
                target_team_name_snapshot=team_name,
            )
            if row.status in _OPEN_STATUSES:
                try:
                    payload = (
                        json.loads(row.execution_payload_json)
                        if not row.execution_payload_encrypted
                        else None
                    )
                except (TypeError, json.JSONDecodeError):
                    payload = None
                if isinstance(payload, dict):
                    payload["target_team_id"] = team_id
                    values["execution_payload_json"] = json.dumps(
                        payload, ensure_ascii=False
                    )
                else:
                    values.update(
                        status="expired",
                        execution_payload_json=None,
                        resolved_at=now,
                    )
        elif row.status in _OPEN_STATUSES:
            values.update(
                status="expired",
                execution_payload_json=None,
                resolved_at=now,
            )
        if values:
            connection.execute(
                pending.update().where(pending.c.id == row.id).values(**values)
            )

    with op.batch_alter_table("assistant_turns", schema=None) as batch_op:
        batch_op.drop_constraint("fk_assistant_turns_context_team_id", type_="foreignkey")
        batch_op.drop_index("ix_assistant_turns_context_team_id")
        batch_op.drop_column("context_team_id")


def downgrade() -> None:
    with op.batch_alter_table("assistant_turns", schema=None) as batch_op:
        batch_op.add_column(sa.Column("context_team_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_assistant_turns_context_team_id",
            "teams",
            ["context_team_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_assistant_turns_context_team_id", ["context_team_id"], unique=False
        )

    connection = op.get_bind()
    pending = sa.table(
        "assistant_pending_actions",
        sa.column("turn_id", sa.Integer()),
        sa.column("target_team_id", sa.Integer()),
        sa.column("status", sa.String()),
    )
    turns = sa.table(
        "assistant_turns",
        sa.column("id", sa.Integer()),
        sa.column("context_team_id", sa.Integer()),
    )
    teams = sa.table("teams", sa.column("id", sa.Integer()))
    existing_team_ids = set(connection.execute(sa.select(teams.c.id)).scalars())
    targets_by_turn: dict[int, set[int]] = {}
    for turn_id, target_team_id in connection.execute(
        sa.select(pending.c.turn_id, pending.c.target_team_id).where(
            pending.c.target_team_id.is_not(None),
            pending.c.status.in_(_OPEN_STATUSES),
        )
    ).all():
        targets_by_turn.setdefault(turn_id, set()).add(target_team_id)
    for turn_id, target_ids in targets_by_turn.items():
        if len(target_ids) != 1:
            continue
        target_team_id = next(iter(target_ids))
        if target_team_id not in existing_team_ids:
            continue
        connection.execute(
            turns.update()
            .where(turns.c.id == turn_id)
            .values(context_team_id=target_team_id)
        )

    op.drop_column("assistant_tool_executions", "target_selector_json")
    with op.batch_alter_table("assistant_pending_actions", schema=None) as batch_op:
        batch_op.drop_index("ix_assistant_pending_actions_target_team_id")
        batch_op.drop_column("target_selector_json")
        batch_op.drop_column("target_team_name_snapshot")
        batch_op.drop_column("target_team_id")

"""add_login_challenges_table

Adds `login_challenges`, backing `SessionService.store_challenge`/`verify_challenge`
(the login Challenge-Response mechanism) with a real table instead of an in-process
dict on `SessionService`. The in-process dict is a per-worker-process singleton, so
under `WEB_CONCURRENCY>1` the `/challenge` request and the follow-up login request
can land on different workers — the second worker's dict never had the challenge the
first worker issued, so legitimate logins fail intermittently. See
`app/models/database_models.py::LoginChallenge` for the full rationale.

Revision ID: 79ea86508f64
Revises: bc617a8e539d
Create Date: 2026-07-14 13:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "79ea86508f64"
down_revision: Union[str, Sequence[str], None] = "bc617a8e539d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_challenges",
        sa.Column("identifier", sa.String(length=255), nullable=False),
        sa.Column("challenge", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("identifier"),
    )
    op.create_index("ix_login_challenges_expires_at", "login_challenges", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_login_challenges_expires_at", table_name="login_challenges")
    op.drop_table("login_challenges")

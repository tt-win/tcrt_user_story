"""add_event_envelope_columns

Revision ID: add_event_envelope_columns
Revises: d4c9a8b7e6f5
Create Date: 2026-07-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_event_envelope_columns'
down_revision: Union[str, Sequence[str], None] = 'd4c9a8b7e6f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new columns for event envelope
    op.add_column('audit_logs', sa.Column('event_code', sa.String(128), nullable=True))
    op.add_column('audit_logs', sa.Column('impact', sa.String(32), nullable=True))
    op.add_column('audit_logs', sa.Column('outcome', sa.String(32), nullable=True))
    op.add_column('audit_logs', sa.Column('schema_version', sa.SmallInteger(), nullable=False, server_default='0'))

    # Add indexes
    op.create_index('ix_audit_logs_event_code', 'audit_logs', ['event_code'], unique=False)
    op.create_index('ix_audit_logs_event_code_timestamp', 'audit_logs', ['event_code', 'timestamp'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index('ix_audit_logs_event_code_timestamp', table_name='audit_logs')
    op.drop_index('ix_audit_logs_event_code', table_name='audit_logs')

    # Drop columns
    op.drop_column('audit_logs', 'schema_version')
    op.drop_column('audit_logs', 'outcome')
    op.drop_column('audit_logs', 'impact')
    op.drop_column('audit_logs', 'event_code')

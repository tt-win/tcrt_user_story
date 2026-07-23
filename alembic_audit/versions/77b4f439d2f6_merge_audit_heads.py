"""merge audit heads

Revision ID: 77b4f439d2f6
Revises: 4e8f3d57b312, add_event_envelope_columns
Create Date: 2026-07-23 00:13:30.335220

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77b4f439d2f6'
down_revision: Union[str, Sequence[str], None] = ('4e8f3d57b312', 'add_event_envelope_columns')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

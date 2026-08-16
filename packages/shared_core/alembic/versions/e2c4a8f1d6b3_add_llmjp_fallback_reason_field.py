"""Add llmjp_fallback_reason field (ELYZA fast fallback: 8s ACK timeout detection)

Revision ID: e2c4a8f1d6b3
Revises: 7cef352f0e11
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2c4a8f1d6b3'
down_revision: Union[str, Sequence[str], None] = '7cef352f0e11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('nazokake_items', sa.Column('llmjp_fallback_reason', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('nazokake_items', 'llmjp_fallback_reason')

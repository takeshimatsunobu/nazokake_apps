"""Add on-demand ELYZA job queue fields (instructions/250)

Revision ID: c82a34711ad1
Revises: ac5c6cd8803f
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c82a34711ad1'
down_revision: Union[str, Sequence[str], None] = 'ac5c6cd8803f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('nazokake_items', sa.Column('elyza_job_status', sa.String(), nullable=True))
    op.add_column('nazokake_items', sa.Column('elyza_job_locked_at', sa.String(), nullable=True))
    op.add_column('nazokake_items', sa.Column('elyza_job_retry_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('nazokake_items', 'elyza_job_retry_count')
    op.drop_column('nazokake_items', 'elyza_job_locked_at')
    op.drop_column('nazokake_items', 'elyza_job_status')

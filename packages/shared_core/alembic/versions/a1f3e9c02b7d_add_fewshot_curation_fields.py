"""Add Few-shot curation fields (Phase2: admin cockpit)

Revision ID: a1f3e9c02b7d
Revises: fix_timestamp_types
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f3e9c02b7d'
down_revision: Union[str, Sequence[str], None] = 'fix_timestamp_types'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('nazokake_items', sa.Column('is_fewshot_selected', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('nazokake_items', sa.Column('fewshot_axis_tag', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('nazokake_items', 'fewshot_axis_tag')
    op.drop_column('nazokake_items', 'is_fewshot_selected')

"""Add review_status/origin_type/source_item_id fields (Phase5/6: feedback loop integration)

Revision ID: d4e8f1a9c3b6
Revises: a1f3e9c02b7d
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8f1a9c3b6'
down_revision: Union[str, Sequence[str], None] = 'a1f3e9c02b7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('nazokake_items', sa.Column('review_status', sa.String(), nullable=True))
    op.create_index(
        op.f('ix_nazokake_items_review_status'), 'nazokake_items', ['review_status'], unique=False
    )
    op.add_column(
        'nazokake_items',
        sa.Column(
            'origin_type', sa.String(), nullable=False, server_default='ai_generated'
        ),
    )
    op.add_column('nazokake_items', sa.Column('source_item_id', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('nazokake_items', 'source_item_id')
    op.drop_column('nazokake_items', 'origin_type')
    op.drop_index(op.f('ix_nazokake_items_review_status'), table_name='nazokake_items')
    op.drop_column('nazokake_items', 'review_status')

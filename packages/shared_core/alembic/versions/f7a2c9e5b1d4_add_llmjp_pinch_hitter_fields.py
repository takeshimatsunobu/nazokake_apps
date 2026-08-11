"""Add llmjp_model_id/llmjp_is_pinch_hitter fields (emergency: Gemini Flash Lite pinch-hitter mode)

Revision ID: f7a2c9e5b1d4
Revises: d4e8f1a9c3b6
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a2c9e5b1d4'
down_revision: Union[str, Sequence[str], None] = 'd4e8f1a9c3b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('nazokake_items', sa.Column('llmjp_model_id', sa.String(), nullable=True))
    op.add_column('nazokake_items', sa.Column('llmjp_is_pinch_hitter', sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('nazokake_items', 'llmjp_is_pinch_hitter')
    op.drop_column('nazokake_items', 'llmjp_model_id')

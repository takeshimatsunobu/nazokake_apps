"""add quality_circuit_breaker_state table

instructions/231で研究記事テーブルをautogenerateした際、QualityCircuitBreakerStateORM
(instructions/182-183で追加済み)に対応するマイグレーションがこれまで一度も
生成されていなかったこと(コードとDBスキーマの乖離)が副次的に判明した。
research_articlesとは無関係な既存の技術的負債のため、別マイグレーションとして分離する。

Revision ID: 0beb78c386a3
Revises: 08547ae7dc0b
Create Date: 2026-07-26 11:11:36.937777

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0beb78c386a3'
down_revision: Union[str, Sequence[str], None] = '08547ae7dc0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('quality_circuit_breaker_state',
    sa.Column('pipeline_id', sa.String(), nullable=False),
    sa.Column('extreme_window', sa.JSON(), nullable=True),
    sa.Column('last_extreme_direction', sa.String(), nullable=True),
    sa.Column('error_window', sa.JSON(), nullable=True),
    sa.Column('last_error_signature', sa.Text(), nullable=True),
    sa.Column('tripped_at', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('pipeline_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('quality_circuit_breaker_state')

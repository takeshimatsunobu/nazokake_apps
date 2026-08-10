"""fix timestamp string comparison

Revision ID: fix_timestamp_types
Revises: 
Create Date: 2026-08-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fix_timestamp_types'
down_revision = 'c82a34711ad1'
branch_labels = None
depends_on = None

def upgrade():
    # SQLiteは ALTER COLUMN を直接サポートしていないため、
    # 実際にはAlembicの batch_alter_table を使用して型変換を行います。
    with op.batch_alter_table('trigger_state', schema=None) as batch_op:
        batch_op.alter_column('last_triggered_at',
               existing_type=sa.VARCHAR(),
               type_=sa.DateTime(),
               existing_nullable=True)

    with op.batch_alter_table('research_articles', schema=None) as batch_op:
        batch_op.alter_column('created_at',
               existing_type=sa.VARCHAR(),
               type_=sa.DateTime(),
               existing_nullable=False)

def downgrade():
    with op.batch_alter_table('research_articles', schema=None) as batch_op:
        batch_op.alter_column('created_at',
               existing_type=sa.DateTime(),
               type_=sa.VARCHAR(),
               existing_nullable=False)

    with op.batch_alter_table('trigger_state', schema=None) as batch_op:
        batch_op.alter_column('last_triggered_at',
               existing_type=sa.DateTime(),
               type_=sa.VARCHAR(),
               existing_nullable=True)

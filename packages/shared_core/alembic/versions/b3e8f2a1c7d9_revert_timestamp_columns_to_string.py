"""Revert research_articles.created_at / trigger_state.last_triggered_at to String

Revision ID: b3e8f2a1c7d9
Revises: f7a2c9e5b1d4
Create Date: 2026-08-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3e8f2a1c7d9'
down_revision = 'f7a2c9e5b1d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema.

    fix_timestamp_types(2026-08-04)がtrigger_state.last_triggered_at /
    research_articles.created_atをVARCHAR→DateTimeへ変換したが、対応する
    ORM(nazokake_core.database)側の型宣言・書き込みコード(いずれも
    datetime.now(timezone.utc).isoformat()でISO8601文字列を代入する既存の
    コードベース全体の規約)は変更されないまま残っていた(models.pyという
    別系統の未使用ORMを新設して型を合わせようとした形跡はあるが、Alembicが
    実際に参照するdatabase.py側のBaseには反映されず、完全なドリフトとして
    放置されていた)。物理スキーマを元のVARCHAR(String)へ戻すことで、
    ORM宣言・書き込みコードの規約と一致させる(fix_timestamp_typesの
    downgrade()と同じ変換をforward migrationとして適用する)。
    """
    with op.batch_alter_table('trigger_state', schema=None) as batch_op:
        batch_op.alter_column('last_triggered_at',
               existing_type=sa.DateTime(),
               type_=sa.VARCHAR(),
               existing_nullable=True)

    with op.batch_alter_table('research_articles', schema=None) as batch_op:
        batch_op.alter_column('created_at',
               existing_type=sa.DateTime(),
               type_=sa.VARCHAR(),
               existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('research_articles', schema=None) as batch_op:
        batch_op.alter_column('created_at',
               existing_type=sa.VARCHAR(),
               type_=sa.DateTime(),
               existing_nullable=False)

    with op.batch_alter_table('trigger_state', schema=None) as batch_op:
        batch_op.alter_column('last_triggered_at',
               existing_type=sa.VARCHAR(),
               type_=sa.DateTime(),
               existing_nullable=True)

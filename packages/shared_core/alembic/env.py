import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# alembic実行時のcwdに依存せず nazokake_core を確実にimportできるよう、
# このファイル(alembic/env.py)から見た packages/shared_core をsys.pathへ追加する。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nazokake_core.database import Base, _resolve_repo_root_default_db_path  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerateがORMモデル(NazokakeItemORM/AuditLogORM)の定義と物理スキーマの差分を
# 検出できるよう、nazokake_core.database の単一のBaseをそのまま束ねる。
target_metadata = Base.metadata


def _resolve_sync_db_url() -> str:
    """nazokake_core.database._resolve_db_url()と同一のルール(環境変数
    NAZOKAKE_DB_PATH優先、未設定時はリポジトリルート直下の絶対パス、
    persona_feature_plan_v3.md §9.1)でDBパスを解決する。

    アプリ本体はaiosqlite(非同期ドライバ)で接続するが、Alembicのマイグレーション
    自体は常駐イベントループを必要としない同期処理のため、標準のsqlite3ドライバ
    (aiosqliteサフィックス無し)へ向ける。
    """
    db_path = os.environ.get("NAZOKAKE_DB_PATH") or _resolve_repo_root_default_db_path()
    return f"sqlite:///{db_path}"


config.set_main_option("sqlalchemy.url", _resolve_sync_db_url())


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # persona_feature_plan_v3.md Phase3: SQLiteはALTER TABLEの機能が限定的
        # (列のADD自体は素で動くが、型変更・制約変更・古いSQLiteでのDROP COLUMN等は
        # 直接サポートしない)。batch_alter_table(新テーブル作成→コピー→差し替え)を
        # 自動的に使わせることで、将来のマイグレーションも含めて安全側に倒す。
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

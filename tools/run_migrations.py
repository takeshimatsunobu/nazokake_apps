"""
tools/run_migrations.py
=========================
Alembicマイグレーション実行ラッパー(インフラ負債解消)。

以下2つのAlembicインフラ負債を解消する:

1. 【並行処理の競合(Race Condition)】run_api.ps1(アプリ起動)とtools/mlops_pipeline_*.py
   (MLOps)が同時にマイグレーションを実行すると、同一SQLiteファイルへの同時スキーマ変更
   (CREATE TABLE/ALTER TABLE等のDDL)が競合し得る。実行前にDBファイルに対応する専用の
   ロックファイルへfilelock.FileLockを取得し、ロック保持中のみマイグレーションを実行する
   ことで、複数プロセスからの同時実行を直列化する(調停ロジック)。

2. 【OSロケール依存のエンコーディングエラー】alembic CLI(`python -m alembic`)は
   alembic.iniをConfigParserで読み込む際、alembic/util/compat.read_config_parser()の
   内部でencoding="locale"を用いる。Windows上ではこれがcp932等になり、日本語コメントを
   含むiniファイルでUnicodeDecodeErrorを起こす(PYTHONUTF8/PYTHONIOENCODING等の環境変数
   では回避できない、明示的なencoding="locale"指定がこれらを上書きするため)。本スクリプトは
   alembic.config.Configをプログラム的に構築し、alembic.iniの読み込みにだけ明示的に
   encoding="utf-8"を指定することで、この問題を構造的に解消する。

使い方:
    uv run python tools/run_migrations.py
"""

from __future__ import annotations

import os
import sys
from configparser import ConfigParser
from pathlib import Path

import filelock
from alembic import command
from alembic.config import Config

if sys.platform == "win32":
    import io

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    import io

    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")

from nazokake_core.database import DEFAULT_DB_PATH  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI_PATH = BASE_DIR / "packages" / "shared_core" / "alembic.ini"
MIGRATION_LOCK_TIMEOUT_SEC = 30


def _load_alembic_config_utf8(ini_path: Path) -> Config:
    """alembic.config.Config を構築する。
    【Fail-Closed】Alembic内部プロパティのオーバーライド(黒魔術)を廃止。
    Python標準のconfigparserでUTF-8読み込み後、Alembic公式のProgrammatic API
    (set_main_option / set_section_option)を用いてクリーンに設定を適用する。
    """

    here = ini_path.resolve().parent.as_posix()
    parser = ConfigParser(defaults={"here": here})

    if not parser.read(str(ini_path), encoding="utf-8"):
        raise FileNotFoundError(
            f"[Fatal] Alembic設定ファイルが見つかりません: {ini_path}"
        )

    cfg = Config()
    cfg.config_file_name = str(ini_path)

    for section in parser.sections():
        for key, value in parser.items(section):
            if key == "here":
                continue  # defaultsで混入した変数はスキップ
            if section == "alembic":
                cfg.set_main_option(key, value)
            else:
                cfg.set_section_option(section, key, value)

    return cfg


def main() -> int:
    db_path = os.environ.get("NAZOKAKE_DB_PATH", DEFAULT_DB_PATH)
    lock_path = f"{db_path}.migration.lock"

    cfg = _load_alembic_config_utf8(ALEMBIC_INI_PATH)

    print(f"🔒 [Alembic] マイグレーションロックの取得を試みます...({lock_path})")
    lock = filelock.FileLock(lock_path, timeout=MIGRATION_LOCK_TIMEOUT_SEC)
    try:
        with lock:
            print("🔒 [Alembic] ロックを取得しました。マイグレーションを実行します...")
            command.upgrade(cfg, "head")
            print("✅ [Alembic] マイグレーションが完了しました。")
    except filelock.Timeout:
        print(
            f"🚨 [Fail-Fast] マイグレーションロックの取得に失敗しました"
            f"({MIGRATION_LOCK_TIMEOUT_SEC}秒待機)。他のプロセスがマイグレーション中の"
            "可能性があります。",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

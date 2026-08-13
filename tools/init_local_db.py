"""
tools/init_local_db.py
========================
ローカルSQLite(Local SSoT)を安全にバックアップ・削除し、
packages/shared_core/nazokake_core/database.py の最新スキーマ(NazokakeItemORM等)で
空のDBを再作成する運用ツール。

スキーマ変更(カラム追加等)のたびにマイグレーションを書く代わりに、開発環境の
ローカルDBを一旦バックアップして作り直すための破壊的操作であるため、以下の
2つの安全装置を必ず経由する:
  1. 実行確認プロンプト('y'/'Y' 以外は即座に中断)
  2. タイムスタンプ付きバックアップ + 5世代ローテーション(古いバックアップの自動削除)

使い方:
    uv run python tools/init_local_db.py
"""

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from nazokake_core.database import (  # noqa: E402
    _resolve_repo_root_default_db_path,
    ensure_db_ready,
)

MAX_BACKUP_GENERATIONS = 5

# SQLite WALモード稼働時に本体ファイルと併存し得るサイドカーファイル。
# 本体を退避・削除する際は、これらも取り残さないよう一緒に処理する。
WAL_SIDECAR_SUFFIXES = ("-wal", "-shm")


def _resolve_db_path() -> Path:
    """database.py と同一のルール(環境変数 NAZOKAKE_DB_PATH 優先、未設定時は
    リポジトリルート直下の絶対パス、persona_feature_plan_v3.md §9.1)でDBパスを解決する。
    """
    return Path(
        os.environ.get("NAZOKAKE_DB_PATH") or _resolve_repo_root_default_db_path()
    ).resolve()


def _confirm(prompt: str) -> bool:
    answer = input(prompt).strip()
    return answer in ("y", "Y")


def _rotate_backups(backup_dir: Path, stem: str) -> None:
    """backup_dir内の '{stem}_*.db.bak' を新しい順に並べ、
    MAX_BACKUP_GENERATIONSを超える古いものを削除する。"""
    pattern = f"{stem}_*.db.bak"
    backups = sorted(backup_dir.glob(pattern), reverse=True)  # ファイル名にタイムスタンプを
    # 含むため、文字列の降順ソート=新しい順になる。
    for stale in backups[MAX_BACKUP_GENERATIONS:]:
        stale.unlink(missing_ok=True)
        print(f"🗑️  古い世代のバックアップを削除しました: {stale.name}")


def _backup_existing_db(db_path: Path) -> Path | None:
    """既存のDBファイルをタイムスタンプ付きでバックアップディレクトリへ退避する。

    WALモードのサイドカー(-wal/-shm)が存在する場合は本体と一緒に退避・削除し、
    本体だけが古い状態のまま取り残される事故を防ぐ。戻り値はバックアップ先パス
    (元ファイルが存在しなかった場合はNone)。
    """
    if not db_path.exists():
        return None

    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}_{timestamp}.db.bak"

    shutil.copy2(db_path, backup_path)
    print(f"💾 バックアップを作成しました: {backup_path}")

    db_path.unlink()
    for suffix in WAL_SIDECAR_SUFFIXES:
        sidecar = db_path.with_name(db_path.name + suffix)
        if sidecar.exists():
            sidecar.unlink()
            print(f"🗑️  WALサイドカーを削除しました: {sidecar.name}")

    _rotate_backups(backup_dir, db_path.stem)
    return backup_path


def main() -> int:
    db_path = _resolve_db_path()
    print(f"対象DB: {db_path}")

    if not _confirm("⚠️ 本当にローカルDBを初期化しますか？(既存データは削除されます) [y/N]: "):
        print("🛑 中断しました(データは一切変更していません)。")
        return 1

    _backup_existing_db(db_path)

    ensure_db_ready()
    print(f"✅ 最新スキーマで新しいDBを作成しました: {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

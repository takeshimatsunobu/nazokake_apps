"""
tools/safe_reset_infra.py
===========================
Local-First SQLite(nazokake_local.db)を安全にスキーマ再構築するための、データ保護型の
リセット・クリーンアップツール。tools/init_local_db.py(バックアップ+再作成)より一段厳格に、
以下を1コマンドで一貫実行する:

  Step 1: psutilでDB本体(+WAL/SHMサイドカー)をロックしているプロセスがいないか検証する。
          検知した場合は自動キルせず、プロセス名/PIDを警告してsys.exit(1)する(フェイルファスト)。
  Step 2: NazokakeItemORMの全レコードを一時JSON(data/db_backup_temp.json)へ退避する
          (DBが存在しない、または0件の場合はスキップする)。
  Step 3: DB本体・WAL/SHM・run/audit_reports/配下・__pycache__系キャッシュ・
          all_source_code.txt を物理削除する。
  Step 4: ensure_db_ready()で最新スキーマのクリーンなDBを再作成し、Step2の一時JSONから
          全件を復元する。復元後、一時JSONは削除する。

使い方:
    uv run python tools/safe_reset_infra.py
"""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import psutil  # noqa: E402
from sqlalchemy import select  # noqa: E402

from nazokake_core.database import (  # noqa: E402
    NazokakeItemORM,
    _resolve_repo_root_default_db_path,
    ensure_db_ready,
    get_session,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_JSON_PATH = PROJECT_ROOT / "data" / "db_backup_temp.json"
WAL_SIDECAR_SUFFIXES = ("-wal", "-shm")
CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache"}
# .git/.venv系/node_modules はベンダー/バイナリ資産であり、この「プロジェクト自身の
# 実行時キャッシュ」クリーンアップの対象外とする(走査コスト・意図の両面で除外が妥当)。
SKIP_DIR_NAMES = {".git", ".venv", ".venv_ai", ".venv_train", "node_modules"}
# DBをロックしうる候補プロセス名の部分一致キーワード(指示書が明示する"python, uvicorn等")。
# 【重要】全プロセスを無差別にProcess.open_files()へ渡すと、Windows上でハンドル列挙が
# ネイティブにクラッシュする(Pythonのtry/exceptで捕捉できないセグメンテーション違反)
# ことを実機で確認済み。対象をDBを開く可能性のあるプロセス名だけに絞ることで、この
# クラッシュを回避しつつ指示書の意図(python/uvicornプロセスの検知)にも忠実になる。
LOCK_CANDIDATE_NAME_KEYWORDS = ("python", "uvicorn")


def _resolve_db_path() -> Path:
    """nazokake_core.database と同一のルール(環境変数 NAZOKAKE_DB_PATH 優先、未設定時は
    リポジトリルート直下の絶対パス、persona_feature_plan_v3.md §9.1)でDBパスを解決する。
    """
    return Path(
        os.environ.get("NAZOKAKE_DB_PATH") or _resolve_repo_root_default_db_path()
    ).resolve()


def check_no_process_locks(paths: list[Path]) -> None:
    """指定パス群(DB本体+WAL/SHMサイドカー)を開いているプロセスが無いか検証する。

    検知した場合はプロセス名/PIDを警告出力し、自動キルは一切行わず即座にsys.exit(1)する
    (フェイルファスト)。他ユーザーのプロセスや権限不足で列挙できないプロセス
    (psutil.AccessDenied等)は、OS側の権限モデルに起因する既知の制約として個別に
    捕捉しスキップする(tools/nazo_agent.py の kill_process_by_port と同じ方針)。

    プロセス名がLOCK_CANDIDATE_NAME_KEYWORDS(python/uvicorn等)に一致するものだけを
    対象にする。全プロセスを無差別にopen_files()へ渡すとWindows上でネイティブに
    クラッシュする(セグメンテーション違反、Python側のtry/exceptでは捕捉不能)ことを
    実機で確認したため、DBを開く可能性が実質的にあるプロセスだけに絞ることで安全性と
    指示書の意図を両立する。
    """
    normalized_targets = {os.path.normcase(str(p)) for p in paths}
    for proc in psutil.process_iter(["pid", "name"]):
        name = (proc.info.get("name") or "").lower()
        if not any(keyword in name for keyword in LOCK_CANDIDATE_NAME_KEYWORDS):
            continue

        try:
            open_files = proc.open_files()
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except Exception as e:
            print(f"⚠️ [排他制御] プロセス情報の取得中にエラーが発生しました: {e}")
            continue

        for f in open_files:
            if os.path.normcase(f.path) in normalized_targets:
                print(
                    "🚨 [フェイルファスト] DBファイルをロックしているプロセスを検知しました: "
                    f"{proc.info['name']} (PID={proc.info['pid']}) が {f.path} を開いています。",
                    file=sys.stderr,
                )
                print(
                    "自動終了(kill)は行いません。該当プロセスを終了してから再実行してください。",
                    file=sys.stderr,
                )
                sys.exit(1)


async def _fetch_all_records() -> list[dict]:
    async with get_session() as session:
        result = await session.execute(select(NazokakeItemORM))
        rows = result.scalars().all()
        return [
            {c.name: getattr(row, c.name) for c in NazokakeItemORM.__table__.columns}
            for row in rows
        ]


async def _restore_records(records: list[dict]) -> None:
    # upsert_item()は呼び出しごとにsync_status/retry_count/updated_atを強制上書きするため、
    # 当時の同期状態・リトライ履歴を保った完全復元にはNazokakeItemORMへ直接insertする。
    async with get_session() as session:
        async with session.begin():
            session.add_all(NazokakeItemORM(**record) for record in records)


def backup_if_needed(db_path: Path, backup_json_path: Path) -> bool:
    """DBが存在し1件以上のレコードがある場合のみ、全レコードをJSONへ退避する。

    戻り値はバックアップを実際に書き出したかどうか(Step4での復元判定に使う)。
    """
    if not db_path.exists():
        print(f"ℹ️  DBファイルが存在しないためバックアップをスキップします: {db_path}")
        return False

    records = asyncio.run(_fetch_all_records())
    if not records:
        print("ℹ️  DBは空のためバックアップをスキップします。")
        return False

    backup_json_path.parent.mkdir(parents=True, exist_ok=True)
    backup_json_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"💾 {len(records)}件のレコードをバックアップしました: {backup_json_path}")
    return True


def purge_infra(db_path: Path, project_root: Path) -> None:
    """メインDB・WAL/SHM・audit_reports配下・実行時キャッシュ・過去のダンプ遺物を物理削除する。"""
    for suffix in ("", *WAL_SIDECAR_SUFFIXES):
        target = db_path.with_name(db_path.name + suffix) if suffix else db_path
        if target.exists():
            target.unlink()
            print(f"🗑️  削除しました: {target}")

    audit_reports_dir = project_root / "run" / "audit_reports"
    if audit_reports_dir.exists():
        shutil.rmtree(audit_reports_dir)
    audit_reports_dir.mkdir(parents=True, exist_ok=True)
    print(f"🗑️  クリアしました(ディレクトリは保持): {audit_reports_dir}")

    for dirpath, dirnames, _filenames in os.walk(project_root, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        for d in list(dirnames):
            if d in CACHE_DIR_NAMES:
                full = Path(dirpath) / d
                shutil.rmtree(full, ignore_errors=True)
                print(f"🗑️  削除しました: {full}")
                dirnames.remove(d)

    dump_file = project_root / "all_source_code.txt"
    if dump_file.exists():
        dump_file.unlink()
        print(f"🗑️  削除しました: {dump_file}")


def rebuild_and_restore(backup_json_path: Path, had_backup: bool) -> None:
    """最新スキーマでDBを再作成し、バックアップがあれば全件復元する。"""
    ensure_db_ready()
    print("✅ 最新スキーマでDBを再作成しました。")

    if not had_backup:
        return

    records = json.loads(backup_json_path.read_text(encoding="utf-8"))
    asyncio.run(_restore_records(records))
    print(f"♻️  {len(records)}件のレコードを復元しました。")

    backup_json_path.unlink()
    print(f"🗑️  一時バックアップファイルを削除しました: {backup_json_path}")


def main() -> int:
    db_path = _resolve_db_path()
    sidecar_paths = [db_path] + [
        db_path.with_name(db_path.name + suffix) for suffix in WAL_SIDECAR_SUFFIXES
    ]

    print("=== Step 1: 排他制御チェック ===")
    check_no_process_locks(sidecar_paths)
    print("✅ ロックなし。続行します。")

    print("=== Step 2: 資産のバックアップ ===")
    had_backup = backup_if_needed(db_path, BACKUP_JSON_PATH)

    print("=== Step 3: インフラの完全パージ ===")
    purge_infra(db_path, PROJECT_ROOT)

    print("=== Step 4: スキーマ再構築とデータ復元 ===")
    rebuild_and_restore(BACKUP_JSON_PATH, had_backup)

    print("🎉 完了しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

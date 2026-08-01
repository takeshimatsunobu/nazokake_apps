"""
tools/preflight_check.py
===========================
決定論的なタスク多重実行ブロック機構(instructions/180、Fail-Closed化はinstructions/181)。

AI(Claude Code)自身の会話コンテキスト・推論に依存した「このタスクはもう完了した
はず」という判断は、要約の欠落や文脈の取り違えによるハルシネーションの温床であり、
同一タスク(instructions/NNN)を誤って重複実行してしまうリスクを構造的に排除できない。
本ツールはAIの推論を一切介さず、run/tasks_state.json(各タスクIDの実行状態と
完了時のコミットハッシュを記録する外部SSoT)を機械的に読むだけで、多重実行を
決定論的にブロックするPre-flight Checkとして機能する。

run/tasks_state.jsonのスキーマ(タスクIDをキーとするdict):
    {
        "task_180": {"status": "done", "commit_hash": "abc1234"},
        "task_181": {"status": "in_progress"}
    }
statusは "todo" / "in_progress" / "done" のいずれか。

【Fail-Closed(SRE監査による差し戻し、instructions/181)】以前の実装は、
run/tasks_state.jsonの不在・JSON破損を「タスク記録なし」として黎明に読み替え、
処理をブロックせず先へ進めていた(Fail-Open)。これは外部SSoT自体が信頼できない
状態にもかかわらず「安全」と誤認して進行してしまう、SSoTの原則そのものを破壊する
アンチパターンである。本改修では、状態ファイルの読み込みに失敗した場合
(FileNotFoundError/json.JSONDecodeError)、不確実な状態での進行を一切許容せず、
即座にsys.exit(1)で後続プロセスを物理的に遮断する。「本来のタスク実行を誤って
ブロックしてしまうリスク」よりも「破損・不在に気づかず多重実行してしまうリスク」の
方が重大という判断に基づく。

【アトミックI/Oと排他ロック(instructions/181)】今後run/tasks_state.jsonを更新する
処理(update_task_state())は、複数プロセスが同時に「読む→更新→書く」を行うと、
後勝ちの書き込みが先勝ちの更新を silently 上書きするレースコンディション、および
書き込み途中のプロセスクラッシュによるJSON破損の両方を引き起こしうる。
filelock.FileLock(タイムアウト付き)でSELECTから書き込みまでの全区間を排他化し、
tempfile+os.fsync+os.replaceのアトミックリネームパターン(tools/ast_modifier.py.
_atomic_write_text、tools/scheduler_daemon.py._atomic_write_json、
tools/mlops_trigger.py._save_last_run_statusと同じ)で書き込む。読み取り側は常に
「更新前の完全な内容」か「更新後の完全な内容」のいずれかしか観測しない。

使い方:
    uv run python tools/preflight_check.py task_180
    # 完了済み(status=="done")の場合はsys.exit(1)、それ以外はsys.exit(0)
    # run/tasks_state.jsonの不在・破損時もsys.exit(1)(Fail-Closed)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import filelock

BASE_DIR = Path(__file__).resolve().parent.parent
TASKS_STATE_PATH = BASE_DIR / "run" / "tasks_state.json"
# ast_modifier.py.FILE_LOCK_TIMEOUT_SECと同じ桁数(小さなJSONファイル1個のみを保護する
# ロックのため、長時間の保持は想定しない)。
TASKS_STATE_LOCK_TIMEOUT_SEC = 10
TASKS_STATE_LOCK_PATH = Path(f"{TASKS_STATE_PATH}.lock")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _load_tasks_state() -> dict:
    """run/tasks_state.jsonを読み込む。

    【Fail-Closed】ファイル不在(FileNotFoundError)・JSON破損(json.JSONDecodeError)
    のいずれも、この関数では一切捕捉せずそのまま呼び出し元へ伝播させる。外部SSoTが
    信頼できない状態を「安全側」に読み替えて処理を続行させることこそが、SREの監査で
    指摘されたFail-Openのアンチパターンだったため、この関数は意図的に「読めなければ
    例外を伝播するだけ」に留める。
    """
    return json.loads(TASKS_STATE_PATH.read_text(encoding="utf-8"))


def is_task_done(task_id: str, tasks_state: dict) -> bool:
    """指定タスクIDのstatusが"done"かどうかを判定する。タスクIDが存在しない、
    またはstatusが"done"以外(todo/in_progress等)の場合はFalse(=未完了として
    実行を許可すべき)を返す。tasks_state.json自体が読めたことは呼び出し元が
    保証済みの前提(Fail-Closed化された_load_tasks_state()を経由済み)であり、
    「タスクIDが未記録」は「状態ファイルが信頼できない」とは異なる正常系である。
    """
    entry = tasks_state.get(task_id)
    if not isinstance(entry, dict):
        return False
    return entry.get("status") == "done"


def update_task_state(task_id: str, status: str, *, commit_hash: str | None = None) -> None:
    """run/tasks_state.jsonへ、指定タスクIDのstatus(と完了時のcommit_hash)を
    排他ロック配下でアトミックに書き込む(instructions/181で確立した、今後の更新
    処理が従うべき設計)。

    filelock.FileLockでSELECT(_load_tasks_state)から書き込みまでの全区間を排他化し、
    複数プロセスが同時に更新した場合の後勝ち上書きによる更新消失を防ぐ。書き込み
    自体はtempfile+os.fsync+os.replaceのアトミックリネームパターンを用い、書き込み
    途中のプロセスクラッシュがtasks_state.jsonを不完全な内容のまま破損させることを
    構造的に防ぐ。_load_tasks_state()と同じFail-Closedの方針を貫くため、既存の
    tasks_state.json自体が読めない(不在・破損)場合もここで例外を握り潰さず、
    そのまま呼び出し元へ伝播させる(壊れた状態の上に新しい更新を書き足して
    誤魔化すことはしない)。
    """
    lock = filelock.FileLock(str(TASKS_STATE_LOCK_PATH), timeout=TASKS_STATE_LOCK_TIMEOUT_SEC)
    with lock:
        tasks_state = _load_tasks_state()
        entry: dict = {"status": status}
        if commit_hash is not None:
            entry["commit_hash"] = commit_hash
        tasks_state[task_id] = entry

        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(TASKS_STATE_PATH.parent), prefix=f".{TASKS_STATE_PATH.name}."
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(tasks_state, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, TASKS_STATE_PATH)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="run/tasks_state.jsonに基づく決定論的なタスク多重実行ブロック"
    )
    parser.add_argument("task_id", help='チェック対象のタスクID(例: "task_180")')
    args = parser.parse_args()

    try:
        tasks_state = _load_tasks_state()
    except FileNotFoundError:
        print(
            f"🚨 [Fail-Closed] {TASKS_STATE_PATH} が存在しません。外部ステートストア"
            "(SSoT)が信頼できない状態のため、安全側に倒して処理を中断します"
            "(instructions/181)。",
            file=sys.stderr,
        )
        return 1
    except json.JSONDecodeError as e:
        print(
            f"🚨 [Fail-Closed] {TASKS_STATE_PATH} のJSONパースに失敗しました({e})。"
            "外部ステートストア(SSoT)が信頼できない状態のため、安全側に倒して処理を"
            "中断します(instructions/181)。",
            file=sys.stderr,
        )
        return 1

    if is_task_done(args.task_id, tasks_state):
        commit_hash = tasks_state[args.task_id].get("commit_hash", "unknown")
        print(
            f"🚨 [Pre-flight Check] タスク '{args.task_id}' は既に完了済みです"
            f"(commit_hash={commit_hash})。多重実行を防ぐため処理を中断します。"
        )
        return 1

    print(f"✅ [Pre-flight Check] タスク '{args.task_id}' は未完了です。実行を継続します。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

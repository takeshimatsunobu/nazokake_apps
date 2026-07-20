"""
tools/preflight_check.py
===========================
決定論的なタスク多重実行ブロック機構(instructions/180)。

AI(Claude Code)自身の会話コンテキスト・推論に依存した「このタスクはもう完了した
はず」という判断は、要約の欠落や文脈の取り違えによるハルシネーションの温床であり、
同一タスク(instructions/NNN)を誤って重複実行してしまうリスクを構造的に排除できない。
本ツールはAIの推論を一切介さず、tools/tasks_state.json(各タスクIDの実行状態と
完了時のコミットハッシュを記録する外部SSoT)を機械的に読むだけで、多重実行を
決定論的にブロックするPre-flight Checkとして機能する。

tools/tasks_state.jsonのスキーマ(タスクIDをキーとするdict):
    {
        "task_180": {"status": "done", "commit_hash": "abc1234"},
        "task_181": {"status": "in_progress"}
    }
statusは "todo" / "in_progress" / "done" のいずれか。このツール自身は
tools/tasks_state.jsonを更新しない(読み取り専用のチェックに徹する。更新は別途、
タスク完了時に呼び出し元が明示的に行う)。

使い方:
    uv run python tools/preflight_check.py task_180
    # 完了済み(status=="done")の場合はsys.exit(1)、それ以外はsys.exit(0)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TASKS_STATE_PATH = BASE_DIR / "tools" / "tasks_state.json"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _load_tasks_state() -> dict:
    """tools/tasks_state.jsonを読み込む。ファイルが存在しない、または内容が壊れて
    いる場合は空のdict(=どのタスクも記録されていない)として安全側に倒す
    (このチェック自身が原因で本来のタスク実行がブロックされてはならないため)。
    """
    if not TASKS_STATE_PATH.exists():
        return {}
    try:
        return json.loads(TASKS_STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def is_task_done(task_id: str, tasks_state: dict) -> bool:
    """指定タスクIDのstatusが"done"かどうかを判定する。タスクIDが存在しない、
    またはstatusが"done"以外(todo/in_progress等)の場合はFalse(=未完了として
    実行を許可すべき)を返す。
    """
    entry = tasks_state.get(task_id)
    if not isinstance(entry, dict):
        return False
    return entry.get("status") == "done"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="tools/tasks_state.jsonに基づく決定論的なタスク多重実行ブロック"
    )
    parser.add_argument("task_id", help='チェック対象のタスクID(例: "task_180")')
    args = parser.parse_args()

    tasks_state = _load_tasks_state()

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

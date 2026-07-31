"""
tools/context_manager.py
============================
Agentの決定論的な長期記憶(instructions/212: Phase 2アーキテクチャリファクタリング)。

【背景】これまでnazo_agent.py(Agent)の実行間で「現在のシステムステート・合意事項・
バックログ」を引き継ぐ仕組みが存在せず、人間がセッション間でコンテキストを手動コピペ
する運用(トイル)に依存していた。本モジュールは、これをrun/context_state.jsonへの
アトミックな読み書きに置き換え、Agent起動時の自動ロード・タスク完了時の自動保存を
可能にする外部SSoTを提供する。

アトミックI/Oと排他ロックの実装は、tools/preflight_check.py(run/tasks_state.json)・
tools/scheduler_daemon.py._atomic_write_jsonと同一のパターン(filelock.FileLockで
読み取りから書き込みまでの全区間を排他化し、tempfile+os.fsync+os.replaceの
アトミックリネームで書き込む)を踏襲する。

【Fail-Closedの適用範囲】run/tasks_state.jsonとは異なり、run/context_state.json
は本モジュール自身が初めて導入する状態ファイルであり、初回実行時点では物理的に
まだ存在しない(これは異常ではなく正常な初期状態)。そのため、
FileNotFoundError(不在)は空のデフォルト状態として扱ってFail-Openする一方、
既存ファイルのJSON破損(json.JSONDecodeError)はtools/preflight_check.pyと同じ方針で
Fail-Closed(例外を伝播)する。「一度も書かれていない」と「書かれたはずのものが
壊れている」は全く異なるリスクだからである。

使い方:
    from tools.context_manager import load_context, save_context

    context = load_context()
    ...  # context["backlog"], context["agreements"], context["system_state"] を参照
    context["backlog"].append("次回: XXXを検証する")
    save_context(context)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import filelock

BASE_DIR = Path(__file__).resolve().parent.parent
CONTEXT_STATE_PATH = BASE_DIR / "run" / "context_state.json"
# tools/preflight_check.py.TASKS_STATE_LOCK_TIMEOUT_SECと同じ桁数(小さなJSONファイル
# 1個のみを保護するロックのため、長時間の保持は想定しない)。
CONTEXT_STATE_LOCK_TIMEOUT_SEC = 10
CONTEXT_STATE_LOCK_PATH = Path(f"{CONTEXT_STATE_PATH}.lock")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _default_context() -> dict[str, Any]:
    """run/context_state.jsonが未だ存在しない(初回実行)場合のデフォルト状態。"""
    return {
        "system_state": {},
        "agreements": [],
        "backlog": [],
        "last_updated": None,
    }


def load_context() -> dict[str, Any]:
    """run/context_state.jsonを読み込む。

    不在(FileNotFoundError)の場合は初回実行とみなし、空のデフォルト状態を返す
    (Fail-Open)。既存ファイルのJSON破損(json.JSONDecodeError)は、外部SSoTが信頼
    できない状態であるため、tools/preflight_check.pyと同じ方針で例外をそのまま
    呼び出し元へ伝播する(Fail-Closed)。
    """
    try:
        return json.loads(CONTEXT_STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _default_context()


def save_context(context: dict[str, Any]) -> None:
    """run/context_state.jsonへ、排他ロック配下でアトミックに書き込む
    (tools/preflight_check.py.update_task_stateと同じtempfile+os.fsync+os.replace
    パターン)。呼び出し元が渡したcontext全体を上書きする(read-modify-writeの
    "modify"部分は呼び出し元の責務)。
    """
    context = {**context, "last_updated": datetime.now(timezone.utc).isoformat()}

    lock = filelock.FileLock(str(CONTEXT_STATE_LOCK_PATH), timeout=CONTEXT_STATE_LOCK_TIMEOUT_SEC)
    with lock:
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(CONTEXT_STATE_PATH.parent), prefix=f".{CONTEXT_STATE_PATH.name}."
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(context, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, CONTEXT_STATE_PATH)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise


def record_agreement(text: str) -> dict[str, Any]:
    """合意事項を1件追加して即座に永続化し、更新後のcontextを返す。"""
    context = load_context()
    context["agreements"].append(text)
    save_context(context)
    return context


def add_backlog_item(item: str) -> dict[str, Any]:
    """バックログ項目を1件追加して即座に永続化し、更新後のcontextを返す。"""
    context = load_context()
    context["backlog"].append(item)
    save_context(context)
    return context


def update_system_state(**kwargs: Any) -> dict[str, Any]:
    """system_stateへキーを1つ以上マージして即座に永続化し、更新後のcontextを返す。"""
    context = load_context()
    context["system_state"].update(kwargs)
    save_context(context)
    return context

"""
tools/shadow_mode.py
========================
データフライホイール(自己修復・学習ループ)の段階的始動(シャドウモード、instructions/182)。

settings.shadow_mode(tools/config.py、既定True)が有効な間、tools/mlops_trigger.py
(MLOpsパイプライン起動トリガー)・tools/nazo_agent.py・tools/agent_graph.py
(Nazo-Agent自己修復ループ)の各副作用ポイント(トリガー状態のDB claim・エフェメラルVM
キック・Gitコミット)は実際の適用を行わず、本モジュール経由で「実行されたはずの内容」
を検証用の別ファイルへ記録するのみに留める。

tools/preflight_check.pyの排他ロック規約(filelock.FileLock、タイムアウト付き)を
踏襲するが、あちらは状態ファイル全体の読み書きを保護するためtempfile+os.fsync+
os.replaceのアトミックリネームパターンを使うのに対し、本モジュールはAppend-onlyな
JSONLログへの追記のみを行うため、そのアトミックリネームは不要(追記区間そのものを
filelockで排他化するだけで、複数プロセスからの同時追記による行の混在を防げる)。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import filelock

BASE_DIR = Path(__file__).resolve().parent.parent
SHADOW_LOG_PATH = BASE_DIR / "tools" / "shadow_mode_log.jsonl"
SHADOW_LOG_LOCK_PATH = Path(f"{SHADOW_LOG_PATH}.lock")
# tools/preflight_check.py.TASKS_STATE_LOCK_TIMEOUT_SECと同じ桁数(小さなログファイル
# 1個への追記のみを保護するロックのため、長時間の保持は想定しない)。
SHADOW_LOG_LOCK_TIMEOUT_SEC = 10


def log_shadow_event(source: str, action: str, details: dict[str, Any]) -> None:
    """シャドウモードで抑止した副作用の内容を、検証用の別ファイル(JSONL、Append-only)
    へ1行追記する。filelock.FileLockでオープンから書き込みまでの区間のみを排他化する
    (複数プロセスからの同時追記に備える)。
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "action": action,
        **details,
    }
    lock = filelock.FileLock(str(SHADOW_LOG_LOCK_PATH), timeout=SHADOW_LOG_LOCK_TIMEOUT_SEC)
    with lock:
        with open(SHADOW_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
    print(
        f"🌑 [Shadow Mode] {source}: {action} を抑止し、検証用ログへ記録しました "
        f"({SHADOW_LOG_PATH})。"
    )

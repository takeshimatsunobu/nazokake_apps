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

【instructions/183: ログの肥大化防止】シャドウモードは既定で常時有効(settings.shadow_mode)
のため、このログはスケジューラの定期サイクル(既定1時間ごと)ごとに無条件で増え続け、
無制限に肥大化する。追記のたびに行数を確認し、MAX_SHADOW_LOG_LINESを超えたら直近N行
のみを残して切り詰める(tools/mlops_trigger.py._save_last_run_statusと同じ
tempfile+os.fsync+os.replaceのアトミック書き換えパターンを踏襲し、切り詰め中のクラッシュで
不完全なJSONLを読み取り側に見せない)。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import filelock

BASE_DIR = Path(__file__).resolve().parent.parent
SHADOW_LOG_PATH = BASE_DIR / "run" / "shadow_mode_log.jsonl"
SHADOW_LOG_LOCK_PATH = Path(f"{SHADOW_LOG_PATH}.lock")
# tools/preflight_check.py.TASKS_STATE_LOCK_TIMEOUT_SECと同じ桁数(小さなログファイル
# 1個への追記のみを保護するロックのため、長時間の保持は想定しない)。
SHADOW_LOG_LOCK_TIMEOUT_SEC = 10
# 【instructions/183】診断用ログの無制限な肥大化を防ぐ行数上限。1回のスケジューラ
# サイクルで数件しか追記されない想定のため、10,000行でも直近数百〜数千サイクル分の
# 診断履歴を確保できる。
MAX_SHADOW_LOG_LINES = 10_000


def _rotate_if_oversized(log_path: Path, max_lines: int) -> None:
    """ログファイルの行数がmax_linesを超えている場合、直近max_lines行のみを残して
    先頭の古い行から切り詰める(instructions/183)。呼び出し元がfilelockを保持した
    状態で呼ぶこと(この区間内で読み書きを完結させ、複数プロセスからの同時追記との
    競合を避ける)。
    """
    if not log_path.exists():
        return
    with open(log_path, encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) <= max_lines:
        return
    trimmed = lines[-max_lines:]
    tmp_path = log_path.with_suffix(".tmp.jsonl")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.writelines(trimmed)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, log_path)


def log_shadow_event(source: str, action: str, details: dict[str, Any]) -> None:
    """シャドウモードで抑止した副作用の内容を、検証用の別ファイル(JSONL、Append-only)
    へ1行追記する。filelock.FileLockでオープンから書き込み・ローテーションまでの区間を
    排他化する(複数プロセスからの同時追記に備える)。
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
        _rotate_if_oversized(SHADOW_LOG_PATH, MAX_SHADOW_LOG_LINES)
    print(
        f"🌑 [Shadow Mode] {source}: {action} を抑止し、検証用ログへ記録しました "
        f"({SHADOW_LOG_PATH})。"
    )

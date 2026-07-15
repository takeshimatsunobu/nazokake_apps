"""
tools/train_unsloth.py
========================
モデル学習スクリプト。Epic 3の「Child Suicide」機構を実装する。

親プロセス(tools/mlops_pipeline.py等のオーケストレーター)が異常終了・強制終了した
場合、学習プロセス自身がVRAMを掴んだままゾンビ化してGPUメモリを解放しない事故を防ぐ
ため、デーモンスレッドで数秒おきに親プロセス(--ppid)の生存を監視し、消失を検知した
瞬間に os._exit(1) で即座に自己終了(VRAM解放)する。

今回は実際のUnslothによる学習ではなく、数秒スリープして終了するモック処理。
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time

import psutil

CHECK_INTERVAL_SEC = 3.0
MOCK_TRAINING_DURATION_SEC = 5.0


def watch_parent(ppid: int, stop_event: threading.Event) -> None:
    """数秒おきにppidの生存を確認し、消失していたら直ちにos._exit(1)する
    (Child Suicide機構)。os._exit()はatexit/finallyを経由しない即時終了であり、
    VRAM解放を最優先する自爆処理としてここでは意図的に使用する。
    """
    while not stop_event.is_set():
        if not psutil.pid_exists(ppid):
            print(
                f"🚨 [Child Suicide] 親プロセス(PID={ppid})が消失しました。"
                "VRAM解放のため即時終了します。",
                file=sys.stderr,
            )
            os._exit(1)
        stop_event.wait(CHECK_INTERVAL_SEC)


def main() -> int:
    parser = argparse.ArgumentParser(description="モデル学習スクリプト(モック)")
    parser.add_argument(
        "--ppid",
        type=int,
        required=True,
        help="親プロセス(オーケストレーター)のPID。消失時にChild Suicideを発動する。",
    )
    args = parser.parse_args()

    stop_event = threading.Event()
    watchdog = threading.Thread(
        target=watch_parent, args=(args.ppid, stop_event), daemon=True
    )
    watchdog.start()

    print(f"🧠 学習を開始します(モック、親PID={args.ppid}をChild Suicide監視中)...")
    time.sleep(MOCK_TRAINING_DURATION_SEC)
    print("✅ 学習が完了しました(モック)。")

    stop_event.set()
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())

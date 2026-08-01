"""
tools/scheduler_daemon.py
============================
mlops-scheduler(サイドカーコンテナ)のENTRYPOINT(instructions/161)。

【Step 3: シグナルハンドリング(PID 1問題の解消)】
旧実装(instructions/160)のbashの無限`sleep`ループは、コンテナのPID 1として実行される
bash自身が`docker stop`が送るSIGTERMを子プロセス(sleep)へ伝播しないため、Docker側の
既定のグレースピリオド(既定10秒)が尽きるまでコンテナが応答不能(ゾンビ化)になり、
最終的にSIGKILLで強制終了させられていた。このスクリプト自身をPID 1として実行し、
signalモジュールでSIGTERM/SIGINTを直接トラップすることで、シグナル受信直後に
Graceful Shutdownできるようにする。

【Step 4: 耐障害性と可観測性】
tools/mlops_trigger.py(内部でさらにtools/mlops_pipeline_nazo.py/agent.pyを起動する)の
クラッシュ・非ゼロ終了・起動自体の失敗は、このデーモンプロセス自身を絶対に落とさない
(次回サイクルまで待って再試行する)。稼働ログはsys.stdoutへ、例外トレースバックは
sys.stderrへ厳格に分離して出力する。ローカルの状態記録(最終実行時刻・終了コード)は
tools/ast_modifier.py._atomic_write_textと同じtempfile+os.replaceパターンでアトミックに
書き込む。

【instructions/169: ブラウザ完結の生存監視】SSH接続無しにこのデーモンの生存を
確認したいというSRE要件に基づき、サイクルごとにtools/export_daemon_heartbeat.py経由で
apps/evaluator/frontend/public/data/daemon_heartbeat.json(admin.html)を更新する。
tools/export_metrics.pyが可視化する「パイプラインの実行結果」とは独立した関心事
(「デーモン自体が生きているか、直前のポーリングで何を決定したか」)を担う。
"""

from __future__ import annotations

import datetime
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from types import FrameType

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from tools import export_daemon_heartbeat  # noqa: E402

INTERVAL_SEC = 3600
STATE_PATH = BASE_DIR / "run" / "scheduler_daemon_state.json"
# tools/mlops_trigger.pyがサイクルごとに書き出す判定結果(閾値未達でスキップ/実際に
# 起動を試みた)。instructions/169: このデーモン自身の生存監視タイル
# (apps/evaluator/frontend/public/data/daemon_heartbeat.json)の材料として読む。
TRIGGER_LAST_RUN_PATH = BASE_DIR / "run" / "mlops_trigger_last_run.json"

_shutdown_requested = False


def _log(message: str) -> None:
    """稼働ログをsys.stdoutへ出力する(異常系のトレースバックとは厳格に分離する)。"""
    print(message, file=sys.stdout, flush=True)


def _handle_shutdown_signal(signum: int, frame: FrameType | None) -> None:
    """SIGTERM/SIGINTを受信した場合、直ちに終了せずフラグを立て、次のポーリング
    間隔(最大1秒)以内に安全に終了する(Graceful Shutdown)。

    このプロセス自身がPID 1としてシグナルを直接トラップするため、旧bash実装の
    「シェルが子プロセスへシグナルを伝播できずコンテナがゾンビ化する」PID 1問題を
    構造的に解消する。
    """
    global _shutdown_requested
    _log(f"🛑 [scheduler_daemon] シグナル{signum}を受信しました。Graceful Shutdownします...")
    _shutdown_requested = True


def _atomic_write_json(path: Path, data: dict) -> None:
    """状態ファイルへのアトミックI/O(tools/ast_modifier.py._atomic_write_textと同じ
    tempfile+os.replaceパターン)。デーモンが書き込み中に強制終了しても、状態ファイルが
    中途半端な内容のまま残ることはない(残るのは書き込み前の旧内容か、書き込み後の
    新内容のみ)。
    """
    dir_name = path.parent
    dir_name.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(dir_name), prefix=f".{path.name}.")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _read_trigger_last_run() -> dict | None:
    """tools/mlops_trigger.pyが直前のサイクルで書き出した判定結果を読む。

    ファイルが存在しない、または内容が壊れている場合はNoneを返す(呼び出し元は
    生存監視タイルの表示を"unknown"へ安全側に倒す)。
    """
    if not TRIGGER_LAST_RUN_PATH.exists():
        return None
    try:
        return json.loads(TRIGGER_LAST_RUN_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _run_trigger_cycle() -> None:
    """tools/mlops_trigger.pyを1サイクルぶんサブプロセスとして実行する。

    サブプロセスの異常終了(非ゼロ終了コード)自体はここでログに残すだけで例外を
    送出しない。サブプロセスの起動自体が失敗した場合(uv不在等)や状態ファイルへの
    書き込み失敗は例外として呼び出し元(main()のループ)へ伝播させ、そちらで一括して
    捕捉する。
    """
    started_at = datetime.datetime.now(datetime.timezone.utc)
    _log(f"🚀 [scheduler_daemon] {started_at.isoformat()} tools/mlops_trigger.py を実行します...")

    result = subprocess.run(
        ["uv", "run", "python", "tools/mlops_trigger.py"],
        cwd=str(BASE_DIR),
    )

    finished_at = datetime.datetime.now(datetime.timezone.utc)
    if result.returncode != 0:
        _log(
            f"⚠️  [scheduler_daemon] {finished_at.isoformat()} tools/mlops_trigger.py が"
            f"異常終了しました(code={result.returncode})。次回サイクルで再試行します。"
        )
    else:
        _log(f"✅ [scheduler_daemon] {finished_at.isoformat()} tools/mlops_trigger.py が正常終了しました。")

    _atomic_write_json(
        STATE_PATH,
        {
            "last_started_at": started_at.isoformat(),
            "last_finished_at": finished_at.isoformat(),
            "last_returncode": result.returncode,
        },
    )

    # 【instructions/169】「デーモンが最後にいつポーリングし、何を決定したか」を
    # ブラウザの管理画面(admin.html)から1クリックで確認できるようにする。
    # tools/mlops_trigger.pyが「閾値未達で何もしなかった(正常)」のか「実際に起動を
    # 試みて失敗した」のかを区別して記録したrun/mlops_trigger_last_run.jsonと、
    # このサブプロセス自体のreturncodeを突き合わせて、生存監視タイルの表示状態を
    # 決定する。
    trigger_last_run = _read_trigger_last_run()
    if result.returncode != 0:
        heartbeat_status = "error"
        heartbeat_message = (
            f"tools/mlops_trigger.pyが異常終了しました(code={result.returncode})。"
        )
    elif trigger_last_run is None:
        heartbeat_status = "unknown"
        heartbeat_message = "tools/mlops_trigger.pyの判定結果ファイルが見つかりませんでした。"
    else:
        heartbeat_status = {
            "skipped": "skipped",
            "triggered": "ok",
            "error": "error",
        }.get(trigger_last_run.get("status"), "unknown")
        heartbeat_message = trigger_last_run.get("message", "")

    export_daemon_heartbeat.export_heartbeat(
        status=heartbeat_status,
        message=heartbeat_message,
        last_cycle_started_at=started_at.isoformat(),
        last_cycle_finished_at=finished_at.isoformat(),
    )


def _interruptible_sleep(seconds: float) -> None:
    """_shutdown_requestedフラグを1秒間隔でポーリングしながらsleepする。

    PEP 475により、Python 3.5以降のtime.sleep()はシグナル受信で中断されず自動的に
    再開される(ブロッキングシステムコールの自動リトライ)。そのため単純な
    `time.sleep(3600)`を1回呼ぶ設計では、シグナル受信から実際の終了まで最大1時間も
    待たされてしまいGraceful Shutdownの意味を失う。短い間隔でポーリングすることで、
    シグナル受信後1秒以内には確実にループを抜けられるようにする。
    """
    deadline = time.monotonic() + seconds
    while not _shutdown_requested and time.monotonic() < deadline:
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)

    _log("🟢 [scheduler_daemon] mlops-schedulerデーモンを起動しました。")

    while not _shutdown_requested:
        try:
            _run_trigger_cycle()
        except Exception:  # noqa: BLE001 - 呼び出し先の予期しない失敗でデーモン自体を落とさない
            # 【Step 4】稼働ログ(sys.stdout)とは厳格に分離し、例外トレースバックは
            # sys.stderrへ出力する。
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            _log(
                "⚠️  [scheduler_daemon] サイクル実行中に予期しない例外を捕捉しました。"
                "デーモン自体は継続します。"
            )

        if _shutdown_requested:
            break
        _interruptible_sleep(INTERVAL_SEC)

    _log("🔚 [scheduler_daemon] Graceful Shutdown完了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

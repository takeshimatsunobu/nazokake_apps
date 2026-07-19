"""
tools/mlops_trigger.py
=========================
イベント駆動のMLOps起動トリガー(Epic 3、instructions/173でステートレス化)。

ローカルDB(なぞかけDPO/SFT候補)とログディレクトリ(Nazo-Agent成功修復ログ)を
スキャンし、閾値を超えたら対応するMLOpsパイプラインをバックグラウンドでキックする。

条件A: なぞかけDPO/SFT候補(tools/extract_dataset.pyと同一の抽出条件:
       human_evaluations が1件以上 または is_golden_data=True)の総件数が
       閾値(settings.mlops_trigger_nazo_threshold、既定500件)以上
       -> tools/mlops_pipeline_nazo.py をキック
条件B: Nazo-Agent成功修復ログ(tools/dataset/agent_sft.jsonlの行数。
       tools/nazo_agent.pyが自己修復に成功するたびに1行追記される)の総件数が
       閾値(settings.mlops_trigger_agent_threshold、既定50件)以上
       -> tools/mlops_pipeline_agent.py をキック

両閾値ともtools/config.pyのToolsSettingsで定義し、環境変数(.env)経由の上書きを
許可する(モジュール内のマジックナンバーとしてハードコードしない)。

【ステートレスな条件評価(instructions/173)】以前は「前回トリガー時点の件数」を
状態ファイル(tools/mlops_trigger_state.json)に記録し、「現在の件数 - 前回
トリガー時点の件数」を未学習件数とみなしていた。この設計はステートフルであり、
毎回のスキャンが「これまでの履歴」に依存してしまう。本モジュールは現在の生カウントを
直接閾値と比較するだけのステートレスな評価へ移行した(状態ファイル自体は廃止)。

両カウントとも学習済みでも減らない単調増加の生カウントであり「学習済みフラグ」が
存在しないため、ステートレス化に伴い「閾値を一度超えた後、データが増えなくても
スケジューラの毎サイクル(既定1時間、tools/scheduler_daemon.py)ごとに再発火して
しまう」という多重発火のリスクが生じる。この対策として、
tools/config.py:MLOPS_PIPELINE_LOCK_PATH というファイルロックの mtime(直前に
実際に起動をキックした時刻)を基準としたクールダウン(既定24時間、
settings.mlops_trigger_cooldown_hours)を設け、クールダウン期間中は閾値超過中でも
新規のキックを見送る。

【排他制御と非同期キック(instructions/173)】閾値に達した場合、まず
MLOPS_PIPELINE_LOCK_PATH のファイルロック(filelock, timeout=0)の取得を試みる。
これは「トリガー自身の多重起動防止」専用の関心事であり、パイプライン自身がGPU使用中に
保持するVRAM_LOCK_PATH(tools/mlops_common.py)とは独立している。ロックが取得できた
場合のみ、asyncio.create_subprocess_exec でパイプラインをバックグラウンドへキックし、
その完了を一切待たずに(ステートレス稼働を厳守し)即座に終了する。両条件が同時に
成立していても、キック自体は順次実行する(A→B、意図が明確でログも追いやすいため)。

使い方:
    uv run python tools/mlops_trigger.py             # スキャンし、条件を満たせばキック
    uv run python tools/mlops_trigger.py --dry-run    # キックせず判定結果のみ表示
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import filelock

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tools.config import MLOPS_PIPELINE_LOCK_PATH, settings  # noqa: E402
from tools.extract_dataset import _fetch_candidates  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

AGENT_SFT_PATH = BASE_DIR / "tools" / "dataset" / "agent_sft.jsonl"

# 【instructions/169】今回のサイクルの判定結果(スキップ/起動、起動した場合は各パイプ
# ラインの成否)をアトミックに書き出す先。tools/scheduler_daemon.pyがこれを読み、
# 「閾値未達で何もしなかった(正常)」と「実際に起動を試みた/失敗した」を区別した上で、
# apps/evaluator/frontend/public/data/daemon_heartbeat.json(admin.htmlの生存監視タイル)
# へ反映する。dry-run実行時は更新しない(診断目的の手動実行がデーモンの実際の稼働状態を
# 上書きしないようにするため)。
LAST_RUN_STATUS_PATH = Path(__file__).resolve().parent / "mlops_trigger_last_run.json"


def _save_last_run_status(status: str, message: str, **details) -> None:
    """このサイクルの判定結果をアトミックに書き出す(tempfile+os.fsync+os.replace、
    tools/ast_modifier.py._atomic_write_textと同じパターン)。書き込み途中の不完全な
    JSONを読み取り側(scheduler_daemon.py)が掴むRace Conditionを防ぐ。
    """
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "message": message,
        **details,
    }
    tmp_path = LAST_RUN_STATUS_PATH.with_suffix(".tmp.json")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, LAST_RUN_STATUS_PATH)


def count_nazo_candidates() -> int:
    """tools/extract_dataset.pyと同一条件のなぞかけDPO/SFT候補の総件数を数える。"""
    candidates = asyncio.run(_fetch_candidates())
    return len(candidates)


def count_agent_success_logs() -> int:
    """Nazo-Agent成功修復ログ(agent_sft.jsonlの行数)を数える。ファイルが無い場合は0件。"""
    if not AGENT_SFT_PATH.exists():
        return 0
    with AGENT_SFT_PATH.open(encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _lock_is_within_cooldown(lock_path: Path, cooldown_hours: float) -> bool:
    """ロックファイルのmtime(直前に実際にキックした時刻)が、直近cooldown_hours
    時間以内かどうかを判定する。ロックファイルが存在しない場合(これまで一度も
    キックしていない)はクールダウン対象外としてFalseを返す。
    """
    if not lock_path.exists():
        return False
    age_sec = time.time() - lock_path.stat().st_mtime
    return age_sec < cooldown_hours * 3600


async def _kick_pipeline_async(script_name: str) -> int:
    """パイプラインを非同期プロセスとしてバックグラウンドでキックし、その完了を
    一切待たずにPIDのみを返す(ステートレス稼働の厳守、instructions/173)。
    """
    print(f"🚀 [Trigger] {script_name} を非同期にバックグラウンドキックします...")
    kwargs: dict = {}
    if sys.platform != "win32":
        # 親(このトリガープロセス)のセッションから明示的に切り離し、トリガー自身の
        # 終了後もパイプラインが影響を受けず生き続けるようにする(POSIX限定の機能。
        # 本番の実行環境(mlops-schedulerサイドカーコンテナ)は常にLinuxである)。
        kwargs["start_new_session"] = True
    process = await asyncio.create_subprocess_exec(
        "uv", "run", "python", f"tools/{script_name}",
        cwd=str(BASE_DIR),
        **kwargs,
    )
    print(f"✅ [Trigger] {script_name} をPID={process.pid}でバックグラウンドキックしました。")
    return process.pid


async def _kick_all(nazo_should_trigger: bool, agent_should_trigger: bool) -> None:
    # 両条件が同時に成立していても、キック自体は順次実行する(A→B)。いずれも
    # 完了を待たないため、この順次実行はキックそのものの発行順のみを意味する。
    if nazo_should_trigger:
        await _kick_pipeline_async("mlops_pipeline_nazo.py")
    if agent_should_trigger:
        await _kick_pipeline_async("mlops_pipeline_agent.py")


def main() -> int:
    parser = argparse.ArgumentParser(description="MLOpsイベント駆動起動トリガー")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際にキックせず、判定結果のみ表示する",
    )
    args = parser.parse_args()

    # 【ステートレスな条件評価】前回トリガー時点からの差分ではなく、現在の生カウントを
    # 直接閾値と比較するだけ(instructions/173)。
    nazo_total = count_nazo_candidates()
    print(
        f"📊 [条件A] なぞかけDPO/SFT候補: 総数={nazo_total} "
        f"(閾値={settings.mlops_trigger_nazo_threshold})"
    )

    agent_total = count_agent_success_logs()
    print(
        f"📊 [条件B] Nazo-Agent成功修復ログ: 総数={agent_total} "
        f"(閾値={settings.mlops_trigger_agent_threshold})"
    )

    nazo_should_trigger = nazo_total >= settings.mlops_trigger_nazo_threshold
    agent_should_trigger = agent_total >= settings.mlops_trigger_agent_threshold

    if not nazo_should_trigger and not agent_should_trigger:
        print("\nℹ️  いずれの条件も未達のため、パイプラインはキックしません。")
        # 【instructions/169のコメントに明記された既存の意図の是正】dry-run実行時は
        # 診断目的の手動実行がデーモンの実際の稼働状態を上書きしないよう、この分岐でも
        # 状態を更新しない(以前はこの早期returnがargs.dry_runのチェックより前にあり、
        # dry-run時でも書き込んでしまっていた)。
        if not args.dry_run:
            _save_last_run_status(
                "skipped", "いずれの条件も未達のため、パイプラインはキックしませんでした。"
            )
        return 0

    if args.dry_run:
        if nazo_should_trigger:
            print("🧪 [dry-run] 条件Aが成立: mlops_pipeline_nazo.py をキックする想定です。")
        if agent_should_trigger:
            print("🧪 [dry-run] 条件Bが成立: mlops_pipeline_agent.py をキックする想定です。")
        return 0

    # 【多重発火防止(クールダウン)】ステートレス化に伴い、閾値超過が続く限り
    # 毎サイクル再発火してしまうリスクをロックファイルのmtime基準で抑止する。
    if _lock_is_within_cooldown(MLOPS_PIPELINE_LOCK_PATH, settings.mlops_trigger_cooldown_hours):
        message = (
            f"直近{settings.mlops_trigger_cooldown_hours}時間以内にキック済みのため、"
            "多重発火防止のため今回はスキップします。"
        )
        print(f"\nℹ️  {message}")
        _save_last_run_status("skipped", message)
        return 0

    # 【排他制御】トリガー自身の多重起動防止(VRAM_LOCK_PATHとは独立した関心事)。
    # timeout=0で即座に判定し、他プロセスが保持中なら待たずにスキップする
    # (このトリガー自体は短時間で完走する設計のため、待機は行わない)。
    lock = filelock.FileLock(str(MLOPS_PIPELINE_LOCK_PATH), timeout=0)
    try:
        with lock:
            try:
                asyncio.run(_kick_all(nazo_should_trigger, agent_should_trigger))
            except OSError as e:
                message = f"パイプラインの起動(プロセス生成)に失敗しました: {e}"
                print(f"\n🚨 {message}")
                _save_last_run_status("error", message)
                return 1
            # キックに成功した場合のみクールダウンの基準点(mtime)を更新する。
            MLOPS_PIPELINE_LOCK_PATH.touch()
    except filelock.Timeout:
        message = "ロックを取得できなかったため、キックをスキップしました(多重起動防止)。"
        print(f"\n⚠️  {message}")
        _save_last_run_status("skipped", message)
        return 0

    _save_last_run_status(
        "triggered",
        "パイプラインの起動をバックグラウンドでキックしました(完了は待ちません)。",
        nazo_triggered=nazo_should_trigger,
        agent_triggered=agent_should_trigger,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

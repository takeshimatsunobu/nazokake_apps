"""
tools/mlops_trigger.py
=========================
イベント駆動のMLOps起動トリガー(Epic 3、instructions/173でステートレス化、
instructions/174でクールダウン状態をDBへ完全移行)。

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
しまう」という多重発火のリスクが生じる。

【永続化層への完全移行(instructions/174)】以前はこの対策としてローカルファイル
(filelockのロックファイルのmtime)への状態依存で代替していたが、SREの絶対要件に
基づきこのアンチパターンを排除し、nazokake_core.database の trigger_state テーブル
(pipeline_id="nazo"/"agent"ごとに1行)へ完全移行した。パイプラインごとに独立して
クールダウンを評価する(旧filelock設計は両パイプラインで1本のロックを共有していた
ため、このDB移行は同時にクールダウンの粒度をパイプライン単位へ精緻化する改善も伴う)。

【CASパターンによるアトミックな状態遷移と、排他制御/クールダウンの分離
(instructions/174追補)】Pythonコード上での「SELECTして判定してからUPDATEする」
という設計は、非同期タスク間のレースコンディションを誘発する。
nazokake_core.database.async_try_claim_trigger_slot() は、以下2つの関心事を
明確に分離した上で、単一のUPSERT文でクールダウン判定・ゾンビ回収・claim奪取を
アトミックに行う:
  - 排他制御(Mutex): trigger_state.status(="running"かどうか)と、
    last_triggered_at(直前にclaimした時刻)からのゾンビ回収
    (settings.mlops_trigger_stale_after_hours、OOM Killer/SIGKILL等でclaimが
    解放されずに残った場合の自動パージ)。
  - 実行間隔制御(Cooldown): last_completed_at(直前に正常完了した時刻)からの
    経過時間のみ(settings.mlops_trigger_cooldown_hours)。パイプライン完了時に
    単に「解放」するだけではこのクールダウンが破壊されてしまうため、statusの
    遷移とは独立してこのカラムだけを正常完了時にのみ更新する
    (nazokake_core.database.async_release_trigger_slot()、
    tools/mlops_pipeline_nazo.py/agent.py側の責務)。

【非同期キック】claimを奪取できた場合のみ、asyncio.create_subprocess_exec で
パイプラインをバックグラウンドへキックし、その完了を一切待たずに(ステートレス
稼働を厳守し)即座に終了する。キック自体が失敗した場合は、stale_after_hoursの
タイムアウトに頼らず即座にclaimを解放する。両条件が同時に成立していても、
キック自体は順次実行する(A→B、意図が明確でログも追いやすいため)。

【Gitリソースの自動ガベージコレクション(instructions/175)】Nazo-Agentの自律
エスカレーション(tools/agent_graph.py)が生成するescalation/*ブランチは、メイン
ブランチへマージされた後もローカルGitに残り続けストレージを圧迫する。人手の
介入なしにパージするため、このトリガーの定期サイクル(scheduler_daemon.pyから
1時間ごとに起動される)に便乗してtools/cleanup_git_resources.pyの
cleanup_merged_git_resources()を毎回呼び出す。削除基準は経過時間ではなく
「メインブランチへのマージ済み」という決定論的な事実のみであり、失敗しても
このトリガー自身の本来の責務(閾値判定・パイプラインキック)を止めない
(dry-run実行時は診断目的の手動実行が意図せずリソースを削除しないよう、
クリーンアップ自体もスキップする)。

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
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from nazokake_core.database import (  # noqa: E402
    async_release_trigger_slot,
    async_try_claim_trigger_slot,
)
from tools.cleanup_git_resources import cleanup_merged_git_resources  # noqa: E402
from tools.config import settings  # noqa: E402
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


async def _try_claim_and_kick(
    pipeline_id: str, script_name: str, cooldown_hours: float, stale_after_hours: float
) -> dict:
    """1つのパイプラインについて、DBのCASクエリでclaim(排他制御+クールダウン
    判定)を試み、成功した場合のみ非同期にバックグラウンドキックする
    (instructions/174追補)。

    claimの奪取自体が成功したにもかかわらずキック(プロセス生成)が失敗した場合は、
    stale_after_hoursのタイムアウトに頼らず、判明した時点で即座にclaimを解放する
    (status="failed")。{"kicked": bool, "claimed": bool, "launch_failed": bool}を
    返す。
    """
    claimed = await async_try_claim_trigger_slot(pipeline_id, cooldown_hours, stale_after_hours)
    if not claimed:
        return {"kicked": False, "claimed": False, "launch_failed": False}

    try:
        await _kick_pipeline_async(script_name)
    except OSError as e:
        print(f"🚨 [Trigger] {script_name} の起動(プロセス生成)に失敗しました: {e}")
        await async_release_trigger_slot(pipeline_id, success=False)
        return {"kicked": False, "claimed": True, "launch_failed": True}

    return {"kicked": True, "claimed": True, "launch_failed": False}


async def _evaluate_and_kick(
    nazo_should_trigger: bool,
    agent_should_trigger: bool,
    cooldown_hours: float,
    stale_after_hours: float,
) -> dict:
    """各条件について、DBのtrigger_state経由で排他制御/クールダウンを評価し、
    claimを奪取できたパイプラインのみを非同期にバックグラウンドキックする
    (instructions/174)。両条件が同時に成立していても、キック自体は順次実行する
    (A→B)。パイプラインごとの結果(_try_claim_and_kickの戻り値)を返す。
    """
    result = {
        "nazo": {"kicked": False, "claimed": False, "launch_failed": False},
        "agent": {"kicked": False, "claimed": False, "launch_failed": False},
    }

    if nazo_should_trigger:
        result["nazo"] = await _try_claim_and_kick(
            "nazo", "mlops_pipeline_nazo.py", cooldown_hours, stale_after_hours
        )

    if agent_should_trigger:
        result["agent"] = await _try_claim_and_kick(
            "agent", "mlops_pipeline_agent.py", cooldown_hours, stale_after_hours
        )

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="MLOpsイベント駆動起動トリガー")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際にキックせず、判定結果のみ表示する",
    )
    args = parser.parse_args()

    # 【instructions/175】マージ済みのescalation/*・draft/*ブランチ/worktreeの
    # ガベージコレクションをこのトリガーの定期サイクルに便乗させる。診断目的の
    # dry-run実行時は意図せずリソースを削除しないようスキップし、失敗しても
    # このトリガー自身の本来の責務(閾値判定)は継続する。
    if not args.dry_run:
        try:
            cleanup_merged_git_resources()
        except Exception as e:  # noqa: BLE001 - クリーンアップ失敗で本来のトリガー評価を止めない
            print(f"⚠️  [Trigger] Gitリソースクリーンアップに失敗しました: {e}")

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
        # dry-run実行時は診断目的の手動実行がデーモンの実際の稼働状態を上書きしない
        # よう、状態を更新しない。
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

    result = asyncio.run(
        _evaluate_and_kick(
            nazo_should_trigger,
            agent_should_trigger,
            settings.mlops_trigger_cooldown_hours,
            settings.mlops_trigger_stale_after_hours,
        )
    )

    if nazo_should_trigger and not result["nazo"]["claimed"]:
        print(
            "\nℹ️  [条件A] 既に実行中、またはクールダウン期間中のため今回はスキップしました。"
        )
    if agent_should_trigger and not result["agent"]["claimed"]:
        print(
            "\nℹ️  [条件B] 既に実行中、またはクールダウン期間中のため今回はスキップしました。"
        )

    any_kicked = result["nazo"]["kicked"] or result["agent"]["kicked"]
    any_launch_failed = result["nazo"]["launch_failed"] or result["agent"]["launch_failed"]

    if not any_kicked and not any_launch_failed:
        message = (
            "対象条件はすべて既に実行中、またはクールダウン期間中のため、"
            "今回はキックをスキップしました。"
        )
        _save_last_run_status("skipped", message)
        return 0

    if any_launch_failed and not any_kicked:
        message = "パイプラインの起動(プロセス生成)に失敗しました。"
        _save_last_run_status("error", message)
        return 1

    _save_last_run_status(
        "triggered",
        "パイプラインの起動をバックグラウンドでキックしました(完了は待ちません)。",
        nazo_triggered=result["nazo"]["kicked"],
        agent_triggered=result["agent"]["kicked"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

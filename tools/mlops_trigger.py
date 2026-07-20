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
    (nazokake_core.database.async_release_trigger_slot()。instructions/177以前は
    tools/mlops_pipeline_nazo.py/agent.py側の責務だったが、下記【エフェメラルVMへの
    同期キック】の通りこのトリガー自身の責務へ移管した)。

【エフェメラルVMへの同期キック(instructions/177で全面改訂)】以前はこのトリガー
自身がGCP VM上のmlops-schedulerサイドカーに常駐し、claimを奪取した場合に
`uv run python tools/{script}.py`をローカルの非同期サブプロセスとしてバック
グラウンドへキックし、その完了を一切待たずに即座に終了していた。しかしこの設計は
「VMが1時間ごとのポーリングのためだけに常時起動し続ける」というFinOps上の課金
リスク・API暴走リスクを常に抱える。instructions/177に基づき、このトリガー自身の
動作環境を「ローカルPC」と再定義し、キック方式を根本的に変更した:
  - claimを奪取した場合のみ、tools/deploy/run_ephemeral_pipeline.ps1を
    サブプロセスとして呼び出す。同スクリプトはGCP VMの起動(冪等)→SSH開通待ち→
    コード転送→対象パイプラインのフォアグラウンド同期実行(完了まで待機)→
    try/finallyによるVMの自律停止(FinOpsフェイルセーフ)を一括して行い、
    パイプライン自身の終了コードをそのまま返す。
  - このトリガー(ローカルPC上のプロセス)は、上記スクリプトの完了(VM起動から
    停止までの全ライフサイクル、実際の学習内容次第で数十分〜数時間規模)を
    そのままawaitで待機する。旧来の「即座に返るfire-and-forgetキック」から
    「VMライフサイクル全体の完了を待機する同期キック」への意図的な設計変更である
    (run_ephemeral_pipeline.ps1のパイプライン実行ステップ自体が意図的に単一実行・
    リトライなしのため、正当な学習失敗を誤って再実行することもない)。
  - 【release責務の移動】claimはこのトリガー(ローカルPC、ローカルの
    nazokake_local.db)が奪取する一方、パイプライン自身はエフェメラルVMのDocker
    コンテナ内(NAZOKAKE_DB_PATH=/workspace/data/nazokake_local.db、ローカルPCとは
    物理的に別のDBファイル)で実行される。パイプライン側が従来通り自分自身の
    trigger_stateを解放しても、それはローカルPC側のclaimが記録された行とは
    別ファイルへの書き込みにしかならず、ローカルPC側のclaimが永久に"running"の
    まま残ってしまう(次回以降のトリガー評価がstale_after_hoursのゾンビ回収に
    頼るまで無期限にブロックされる)。この不整合を避けるため、releaseの責務を
    このトリガー自身(_try_claim_and_kick、claimと同じローカルDBへ書き込む)に
    移した。両条件が同時に成立していても、キック自体は順次実行する
    (A→B、意図が明確でログも追いやすいため)。

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

【ローカル排他制御(instructions/178)】このトリガー自身が(cronの二重起動・手動と
スケジューラの重複実行等で)同時に複数プロセスとして起動された場合、それぞれが
独立にVMプロビジョニング(tools/deploy/run_ephemeral_pipeline.ps1)を試みてしまい、
同一VM上での競合や不要な多重課金を招く。trigger_stateのDB CASだけでは
「VMをキックする権利」自体の多重実行(閾値評価・Gitクリーンアップ等の重複実行も含む)
を防げないため、run/.vm_provision.lock(filelock、timeout=0)による決定論的な
ローカル排他制御を追加した。既にロックが取得されている場合は競合とみなし、
エラーではなく正常系として何もせずExit 0する(他プロセスが既に処理中であり、
このプロセスが何もしないことこそが正しい振る舞いのため)。

【instructions/182: シャドウモード】settings.shadow_mode(既定True)が有効な間は、
条件が成立してもDBのトリガー状態claim・エフェメラルVMキックを一切行わず、判定結果を
tools/shadow_mode_log.jsonlへ記録するのみに留める(--dry-runとは独立した、既定で
有効な安全弁)。--shadow-mode/--no-shadow-modeでこのプロセス単体の実行時に上書きできる。

使い方:
    uv run python tools/mlops_trigger.py                # スキャンし、条件を満たせばキック
                                                          # (既定ではシャドウモードのため実際には抑止される)
    uv run python tools/mlops_trigger.py --dry-run       # キックせず判定結果のみ表示
    uv run python tools/mlops_trigger.py --no-shadow-mode  # シャドウモードを無効化して実際にキックする
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import filelock

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from nazokake_core.database import (  # noqa: E402
    async_release_trigger_slot,
    async_try_claim_trigger_slot,
)
from tools import shadow_mode  # noqa: E402
from tools.cleanup_git_resources import cleanup_merged_git_resources  # noqa: E402
from tools.config import settings  # noqa: E402
from tools.extract_dataset import _fetch_candidates  # noqa: E402

# 【instructions/178】このトリガー自身の多重実行を防ぐローカル排他ロック。run/は
# tools/mlops_common.pyのVRAM_LOCK_PATHと同じ揮発層の慣習に合わせた既存ディレクトリ
# (.gitkeep付き)であり、新規作成は不要。
VM_PROVISION_LOCK_PATH = BASE_DIR / "run" / ".vm_provision.lock"

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


EPHEMERAL_DEPLOY_SCRIPT_PATH = BASE_DIR / "tools" / "deploy" / "run_ephemeral_pipeline.ps1"


async def _run_ephemeral_pipeline_async(script_name: str) -> int:
    """指定のMLOpsパイプラインを、tools/deploy/run_ephemeral_pipeline.ps1経由で
    エフェメラルGCP VM上でフォアグラウンド同期実行し、その完了(VM起動→SSH開通待ち→
    コード転送→パイプライン実行→VM自律停止の全ライフサイクル)を待機してから
    パイプライン自身の終了コードを返す(instructions/177)。

    VM起動・SSH開通・転送のいずれかで失敗した場合(Step 5に到達できなかった場合)は
    run_ephemeral_pipeline.ps1の仕様により終了コード1が返る。この関数自体は
    powershell.exeの起動(プロセス生成)にOSError相当の失敗が無い限り例外を送出しない
    (プロセス生成自体の失敗は呼び出し元の_try_claim_and_kickがOSErrorとして捕捉する)。
    """
    print(
        f"🚀 [Trigger] {script_name} をエフェメラルVM上で起動します"
        "(VM起動→同期実行→自律停止、完了まで待機します)..."
    )
    process = await asyncio.create_subprocess_exec(
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(EPHEMERAL_DEPLOY_SCRIPT_PATH),
        "-PipelineScript", script_name,
        cwd=str(BASE_DIR),
    )
    returncode = await process.wait()
    if returncode == 0:
        print(f"✅ [Trigger] {script_name} がエフェメラルVM上で正常終了しました。")
    else:
        print(
            f"🚨 [Trigger] {script_name} がエフェメラルVM上で異常終了しました"
            f"(exit={returncode})。"
        )
    return returncode


async def _try_claim_and_kick(
    pipeline_id: str, script_name: str, cooldown_hours: float, stale_after_hours: float
) -> dict:
    """1つのパイプラインについて、DBのCASクエリでclaim(排他制御+クールダウン
    判定)を試み、成功した場合のみエフェメラルVM上で同期実行する
    (instructions/174追補、VMキックへの改訂はinstructions/177)。

    claimの奪取自体が成功したにもかかわらずキック(powershell.exeのプロセス生成)
    自体が失敗した場合、またはVM上でのパイプライン実行自体が非ゼロ終了した場合は、
    いずれもstale_after_hoursのタイムアウトに頼らず、判明した時点で即座にclaimを
    解放する(status="failed")。

    【release責務(instructions/177)】claim(async_try_claim_trigger_slot)は
    ローカルPC上のこのプロセスがローカルのnazokake_local.dbに対して行うが、
    パイプライン自身はエフェメラルVMのDockerコンテナ内(物理的に別のDBファイル)で
    実行される。パイプライン側の自己releaseに委ねるとclaimと異なるDBへの書き込みに
    なってしまうため、claimと対称なreleaseはこのトリガー自身(=claimと同じDBに
    書き込める場所)の責務とする。

    {"kicked": bool, "claimed": bool, "launch_failed": bool}を返す。claimed=Trueの
    場合、kickedとlaunch_failedは排他的(kicked=Trueは「VM起動からパイプライン正常
    終了まで完全に成功した」場合のみ)。
    """
    claimed = await async_try_claim_trigger_slot(pipeline_id, cooldown_hours, stale_after_hours)
    if not claimed:
        return {"kicked": False, "claimed": False, "launch_failed": False}

    try:
        returncode = await _run_ephemeral_pipeline_async(script_name)
    except OSError as e:
        print(f"🚨 [Trigger] {script_name} の起動(プロセス生成)に失敗しました: {e}")
        await async_release_trigger_slot(pipeline_id, success=False)
        return {"kicked": False, "claimed": True, "launch_failed": True}

    success = returncode == 0
    await async_release_trigger_slot(pipeline_id, success=success)
    if not success:
        return {"kicked": False, "claimed": True, "launch_failed": True}

    return {"kicked": True, "claimed": True, "launch_failed": False}


async def _evaluate_and_kick(
    nazo_should_trigger: bool,
    agent_should_trigger: bool,
    cooldown_hours: float,
    stale_after_hours: float,
) -> dict:
    """各条件について、DBのtrigger_state経由で排他制御/クールダウンを評価し、
    claimを奪取できたパイプラインのみをエフェメラルVM上で同期実行する
    (instructions/174、VMキックへの改訂はinstructions/177)。両条件が同時に
    成立していても、キック自体は順次実行する(A→B)。パイプラインごとの結果
    (_try_claim_and_kickの戻り値)を返す。
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


def _run_trigger_cycle(args: argparse.Namespace) -> int:
    """このトリガーの1サイクル分の本体(閾値評価・Gitクリーンアップ・エフェメラルVM
    キック)。main()がrun/.vm_provision.lock(instructions/178)を取得した状態でのみ
    呼び出す(このプロセス単体では多重実行を想定しない前提のロジック)。
    """
    # 【instructions/175】マージ済みのescalation/*・draft/*ブランチ/worktreeの
    # ガベージコレクションをこのトリガーの定期サイクルに便乗させる。診断目的の
    # dry-run実行時は意図せずリソースを削除しないようスキップし、失敗しても
    # このトリガー自身の本来の責務(閾値判定)は継続する。
    # 【instructions/176】マージ判定はgit branch --mergedの祖先関係に加え、Squash
    # Merge等でコミットハッシュが変わったケースもgit cherryの等価パッチ検出で
    # カバーするよう堅牢化した(cleanup_git_resources.py側)。このトリガー自身の
    # --dry-runとは独立して、環境変数DRY_RUN=trueを設定するだけでも
    # cleanup_merged_git_resources()単体を検証実行(実際の削除なし)できる。
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

    # 【instructions/182: シャドウモード】--dry-runとは独立した、既定で有効な安全弁
    # (settings.shadow_mode)。--dry-runは診断目的で明示的にオプトインする手動フラグ
    # (既定オフ)だが、シャドウモードは自律スケジューラー(tools/scheduler_daemon.py)
    # 経由の定期実行でも既定で効く安全側のデフォルトであり、意味が異なるため統合しない。
    # DBのトリガー状態claimもエフェメラルVMキックも一切行わず、判定結果のみを
    # 検証用ログ(tools/shadow_mode_log.jsonl)へ記録する。
    effective_shadow_mode = (
        settings.shadow_mode if args.shadow_mode is None else args.shadow_mode
    )
    if effective_shadow_mode:
        shadow_mode.log_shadow_event(
            "mlops_trigger",
            "vm_kick_suppressed",
            {
                "nazo_total": nazo_total,
                "nazo_threshold": settings.mlops_trigger_nazo_threshold,
                "nazo_should_trigger": nazo_should_trigger,
                "agent_total": agent_total,
                "agent_threshold": settings.mlops_trigger_agent_threshold,
                "agent_should_trigger": agent_should_trigger,
            },
        )
        _save_last_run_status(
            "shadow_skipped",
            "シャドウモードが有効なため、DBのトリガー状態claim・エフェメラルVMキックを"
            "抑止しました(判定結果はtools/shadow_mode_log.jsonlへ記録済み)。",
            nazo_should_trigger=nazo_should_trigger,
            agent_should_trigger=agent_should_trigger,
        )
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
        message = (
            "パイプラインの起動に失敗しました(VM/SSH/転送等の前段でのプロセス生成"
            "失敗、またはエフェメラルVM上でのパイプライン自体の異常終了)。"
        )
        _save_last_run_status("error", message)
        return 1

    _save_last_run_status(
        "triggered",
        "エフェメラルVM上でのパイプライン実行が完了しました"
        "(instructions/177: VM起動→同期実行→自律停止まで待機済み)。",
        nazo_triggered=result["nazo"]["kicked"],
        agent_triggered=result["agent"]["kicked"],
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="MLOpsイベント駆動起動トリガー")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際にキックせず、判定結果のみ表示する",
    )
    shadow_mode_group = parser.add_mutually_exclusive_group()
    shadow_mode_group.add_argument(
        "--shadow-mode",
        dest="shadow_mode",
        action="store_true",
        default=None,
        help="DBのトリガー状態claim・エフェメラルVMキックを抑止する(instructions/182、"
        "未指定時はsettings.shadow_mode(既定True)に従う)",
    )
    shadow_mode_group.add_argument(
        "--no-shadow-mode",
        dest="shadow_mode",
        action="store_false",
        help="シャドウモードを無効化し、実際にDB claim・エフェメラルVMキックを行う",
    )
    args = parser.parse_args()

    # 【instructions/178】run/.vm_provision.lock(timeout=0)で、このトリガー自身の
    # 多重実行を排除する。他プロセスが既にロックを保持している場合は競合とみなし、
    # エラーではなく正常系として何もせずExit 0する(tools/run_migrations.pyの
    # filelock.Timeout捕捉パターンを踏襲)。
    lock = filelock.FileLock(str(VM_PROVISION_LOCK_PATH), timeout=0)
    try:
        with lock:
            return _run_trigger_cycle(args)
    except filelock.Timeout:
        print(
            "ℹ️  [Trigger] 他のtools/mlops_trigger.pyが既にロックを保持しているため、"
            "多重プロビジョニングを避けて何もせず終了します(instructions/178)。"
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())

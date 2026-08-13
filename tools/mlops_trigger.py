"""
tools/mlops_trigger.py
=========================
【🛑 RETIRED 2026-08-13】このトリガーは無効化されている。

commit b2b22d9「chore(infra): enforce CI/CD SSoT, remove backdoor, setup GH
actions」(2026-08-04)が、このモジュールの前提だった tools/extract_dataset.py
(コアーセット・リプレイ選定/MinHash LSH重複排除/DPOペア化を含む本格的な抽出
パイプライン)と tools/extract_agent_sft.py を削除した。これにより本モジュールは
起動時に ModuleNotFoundError でクラッシュする状態が2026-08-04以降続いていた。

tools/extract_training_data.py はこの穴を埋める代替ではない(同ファイルの
docstringが明言する通り、コアーセット・リプレイ/DPOペア化を持たない別目的の
軽量な補助スクリプト)。つまり _fetch_candidates 相当の抽出ロジックはリポジトリ
上に存在しない。

加えて、このトリガーが駆動する best-of-N/DPO学習パイプラインそのものが、
CLAUDE.md §5に記載の通りbest-of-1へ既に置き換えられており、リポジトリ内の
別の場所(tools/apply_best_of_n_safeguards_v3.py等)でも同系統のロジックが
隔離(quarantine)対象として扱われている最中だった。

以上を2026-08-13にユーザーへ提示し、「抽出ロジックを復元して復旧する」のではなく
「このトリガー自体を退役させる」方針が選択された。そのため以下は、旧
ModuleNotFoundErrorに代えて、起動時に即座に安全へ抜ける退役ガードのみを残し、
DBのtrigger_state claimもエフェメラルVMキックも二度と行わない。

以下は退役前の設計ドキュメントとして参照用に残す(実際のロジックは
main()冒頭の退役ガードにより到達しない)。

---

イベント駆動のMLOps起動トリガー(Epic 3、instructions/173でステートレス化、
instructions/174でクールダウン状態をDBへ完全移行)。

ローカルDB(なぞかけDPO/SFT候補)とログディレクトリ(Nazo-Agent成功修復ログ)を
スキャンし、閾値を超えたら対応するMLOpsパイプラインをバックグラウンドでキックする。

条件A: なぞかけDPO/SFT候補(tools/extract_dataset.pyと同一の抽出条件:
       human_evaluations が1件以上 または is_golden_data=True)の総件数が
       閾値(settings.mlops_trigger_nazo_threshold、既定500件)以上
       -> tools/mlops_pipeline_nazo.py をキック
条件B: Nazo-Agent成功修復ログ(run/dataset/agent_sft.jsonlの行数。
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
run/shadow_mode_log.jsonlへ記録するのみに留める(--dry-runとは独立した、既定で
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
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from nazokake_core.database import (  # noqa: E402
    async_get_circuit_breaker_tripped_at,
    async_release_trigger_slot,
    async_try_claim_trigger_slot,
)
from tools import shadow_mode  # noqa: E402
from tools.cleanup_git_resources import cleanup_merged_git_resources  # noqa: E402
from tools.config import settings  # noqa: E402

# 【🛑 RETIRED 2026-08-13】tools.extract_dataset は commit b2b22d9 で削除済み。
# count_nazo_candidates() はもはや呼び出されない(main()冒頭の退役ガード参照)ため、
# 復活させる代わりにインポート自体を削除した。

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
LAST_RUN_STATUS_PATH = BASE_DIR / "run" / "mlops_trigger_last_run.json"

# 【instructions/298: Graceful Shutdown】このトリガーはscheduler_daemon.py(またはOS/
# Dockerデーモン)からSIGTERM/SIGINTを受けうる。単発CLIのためscheduler_daemon.pyのような
# ポーリングループは持たないが、パイプラインキック中の子プロセス(_active_process、
# PowerShell経由のエフェメラルVM実行、またはLinux直接実行のuv run python)は数十分〜
# 数時間に及びうるため、シグナル受信時に子プロセスを直ちに終了させ、claimしたtrigger_state
# を"running"のまま放置しない(stale_after_hoursのタイムアウト頼みにしない)。
_shutdown_requested = False
_active_process: "asyncio.subprocess.Process | None" = None


def _handle_shutdown_signal(signum: int, frame: FrameType | None) -> None:
    """SIGTERM/SIGINT受信時、直ちに終了せずフラグを立てた上で、実行中の子プロセスが
    あれば直ちにterminateする(Graceful Shutdown)。

    子プロセスの終了自体はここでは待たない(このハンドラは同期コンテキストで動作する
    ため await できない)。呼び出し元の `await process.wait()` が子プロセスの終了を
    検知した時点で、_try_claim_and_kick の既存ロジック(success=Falseでのrelease)が
    そのままclaimの解放を担う(冪等性を損なわない)。
    """
    global _shutdown_requested
    _shutdown_requested = True
    print(
        f"🛑 [Trigger] シグナル{signum}を受信しました。Graceful Shutdownします"
        "(実行中のパイプラインがあれば終了させます)...",
        file=sys.stderr,
    )
    if _active_process is not None and _active_process.returncode is None:
        try:
            _active_process.terminate()
        except ProcessLookupError:
            pass


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
    """【🛑 RETIRED】tools/extract_dataset.py削除(commit b2b22d9)により抽出ロジック
    自体が存在しない。main()冒頭の退役ガードによりこの関数はもはや呼ばれない。
    """
    raise RuntimeError(
        "tools/mlops_trigger.py は退役済みです。count_nazo_candidates() は"
        "tools/extract_dataset.py(commit b2b22d9で削除)に依存していたため、"
        "呼び出し不能な状態のまま残しています。"
    )


def count_agent_success_logs() -> int:
    """Nazo-Agent成功修復ログ(agent_sft.jsonlの行数)を数える。ファイルが無い場合は0件。"""
    if not AGENT_SFT_PATH.exists():
        return 0
    with AGENT_SFT_PATH.open(encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


EPHEMERAL_DEPLOY_SCRIPT_PATH = BASE_DIR / "tools" / "deploy" / "run_ephemeral_pipeline.ps1"


def _resolve_uv_executable() -> str:
    """uvコマンドの絶対パスをshutil.whichで決定論的に解決する(instructions/298)。

    サブプロセス生成時のコマンド名解決をシェル/OSのPATH探索に暗黙に委ねると、
    イメージのビルド時と実行時でPATHの構成がズレた場合に原因特定が難しい失敗を
    招くため、起動前に明示的な絶対パスへ解決し、見つからない場合は
    FileNotFoundErrorとして早期に(実際にサブプロセスを起動する前に)失敗させる。
    """
    uv_path = shutil.which("uv")
    if uv_path is None:
        raise FileNotFoundError(
            "uvコマンドが見つかりません(PATHにuvが存在しません)。"
            "infra/verification_env/mlops_scheduler.Dockerfileのuv導入手順を確認してください。"
        )
    return uv_path


async def _run_ephemeral_pipeline_windows_async(script_name: str) -> int:
    """指定のMLOpsパイプラインを、tools/deploy/run_ephemeral_pipeline.ps1経由で
    エフェメラルGCP VM上でフォアグラウンド同期実行し、その完了(VM起動→SSH開通待ち→
    コード転送→パイプライン実行→VM自律停止の全ライフサイクル)を待機してから
    パイプライン自身の終了コードを返す(instructions/177)。Windows(ローカルPC)専用の
    経路であり、_run_pipeline_asyncからのみ呼ばれる(instructions/298でOS分岐)。

    VM起動・SSH開通・転送のいずれかで失敗した場合(Step 5に到達できなかった場合)は
    run_ephemeral_pipeline.ps1の仕様により終了コード1が返る。この関数自体は
    powershell.exeの起動(プロセス生成)にOSError相当の失敗が無い限り例外を送出しない
    (プロセス生成自体の失敗は呼び出し元の_try_claim_and_kickがOSErrorとして捕捉する)。
    """
    global _active_process
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
    _active_process = process
    try:
        returncode = await process.wait()
    finally:
        _active_process = None
    if returncode == 0:
        print(f"✅ [Trigger] {script_name} がエフェメラルVM上で正常終了しました。")
    else:
        print(
            f"🚨 [Trigger] {script_name} がエフェメラルVM上で異常終了しました"
            f"(exit={returncode})。"
        )
    return returncode


async def _run_pipeline_linux_direct_async(script_name: str) -> int:
    """Linux(sys.platform == "linux")では、Windows専用のPowerShell経由エフェメラルVM
    キック(instructions/177、tools/deploy/run_ephemeral_pipeline.ps1)を行わない
    (instructions/298: OS境界修復)。

    このコードパスは、infra/verification_env/mlops_scheduler.Dockerfileがビルドする
    mlops-schedulerサイドカー(Linuxコンテナ)自身の中でtools/scheduler_daemon.py経由
    このスクリプトが実行された場合に通る。当該コンテナにpowershell.exeは存在せず、
    さらに別のVMを起動する設計上の意味も無いため、shutil.whichで決定論的に解決した
    uvの絶対パスでパイプラインスクリプトを直接サブプロセス実行する。
    """
    global _active_process
    uv_executable = _resolve_uv_executable()
    print(
        f"🚀 [Trigger] {script_name} をLinux環境で直接起動します"
        f"(uv={uv_executable}、PowerShellを介さない、instructions/298)..."
    )
    process = await asyncio.create_subprocess_exec(
        uv_executable, "run", "python", f"tools/{script_name}",
        cwd=str(BASE_DIR),
    )
    _active_process = process
    try:
        returncode = await process.wait()
    finally:
        _active_process = None
    if returncode == 0:
        print(f"✅ [Trigger] {script_name} が正常終了しました。")
    else:
        print(f"🚨 [Trigger] {script_name} が異常終了しました(exit={returncode})。")
    return returncode


async def _run_pipeline_async(script_name: str) -> int:
    """OSに応じてパイプライン起動方式を切り替えるディスパッチャ(instructions/298)。

    Windows(instructions/177が前提とするローカルPC): 従来通りPowerShell経由で
    エフェメラルGCP VMをフルライフサイクルでキックする。
    Linux(mlops-schedulerサイドカーコンテナ自身): PowerShellが存在しないため、
    uvの絶対パスを解決した直接サブプロセス実行へ分岐する。
    """
    if sys.platform == "win32":
        return await _run_ephemeral_pipeline_windows_async(script_name)
    return await _run_pipeline_linux_direct_async(script_name)


# 【instructions/183: 事前遮断ゲート(Pre-flight Gate)】各トリガーpipeline_id("nazo"/
# "agent")の学習データは、apps/batch_factory(なぞかけ生成)が追跡する品質サーキット
# ブレーカー(instructions/182、pipeline_id="batch_factory_generation:{model_name}")の
# 健全性に依存する。ブレーカーがTrip中(サイレント・デグレード検知済み)のまま
# エフェメラルVMをキックすると、劣化したモデルの出力を再学習し続けるクラッシュループ
# 的なクラウドコスト暴走を招くため、キック前に必ずTrip状態を確認する。"nazo"は
# Gemini/LocalUnslothの両生成系列が学習データの源泉であり、いずれかがTrip中でも
# 遮断する。"agent"(tools/nazo_agent.py)は現時点でこのサーキットブレーカーへの
# 配線が存在しないため、対象は空(将来配線されればこのマッピングを更新するだけで
# 自然にゲートが効くようになる)。
_CIRCUIT_BREAKER_SOURCE_PIPELINE_IDS: dict[str, tuple[str, ...]] = {
    "nazo": ("batch_factory_generation:Gemini", "batch_factory_generation:LocalUnsloth"),
    "agent": (),
}


async def _find_tripped_circuit_breaker(pipeline_id: str) -> str | None:
    """pipeline_id(トリガー側の"nazo"/"agent")に対応する品質サーキットブレーカーの
    いずれかがTrip済み(tripped_at != None)であれば、そのtripped_atを返す。
    どれもTripしていない(または対象が存在しない)場合はNoneを返す。
    """
    for source_id in _CIRCUIT_BREAKER_SOURCE_PIPELINE_IDS.get(pipeline_id, ()):
        tripped_at = await async_get_circuit_breaker_tripped_at(source_id)
        if tripped_at is not None:
            return tripped_at
    return None


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

    【instructions/183: 事前遮断ゲート】claimを試みる前に、対象パイプラインに
    対応する品質サーキットブレーカーがTrip中かどうかを確認する。Trip中の場合は
    claim自体も試みず(=クールダウンを無駄に消費させず、次回の正常評価に備える)、
    即座に{"circuit_breaker_tripped": True}を含む未キック状態を返す。呼び出し元の
    _run_trigger_cycleはこれを「何もキックしなかった」通常系として扱い、最終的に
    Exit 0で終了する。
    """
    tripped_at = await _find_tripped_circuit_breaker(pipeline_id)
    if tripped_at is not None:
        print(
            f"🚨 [Pre-flight Gate] pipeline_id={pipeline_id!r} は品質サーキットブレーカーが"
            f"Trip済み(tripped_at={tripped_at})のため、エフェメラルVMのキックをスキップし"
            "ます(instructions/183: クラッシュループによるクラウドコスト暴走の防止)。"
        )
        return {
            "kicked": False,
            "claimed": False,
            "launch_failed": False,
            "circuit_breaker_tripped": True,
        }

    claimed = await async_try_claim_trigger_slot(pipeline_id, cooldown_hours, stale_after_hours)
    if not claimed:
        return {"kicked": False, "claimed": False, "launch_failed": False}

    try:
        returncode = await _run_pipeline_async(script_name)
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

    # 【instructions/298: Graceful Shutdown】シグナル受信後は、既にclaimして実行中の
    # パイプライン(あれば)の終了を待つのみとし、新規のclaim・キックは開始しない。
    if nazo_should_trigger and not _shutdown_requested:
        result["nazo"] = await _try_claim_and_kick(
            "nazo", "mlops_pipeline_nazo.py", cooldown_hours, stale_after_hours
        )

    if agent_should_trigger and not _shutdown_requested:
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
    # dry-run実行時は意図せずリソースを削除しないようスキップする。
    # 【instructions/176】マージ判定はgit branch --mergedの祖先関係に加え、Squash
    # Merge等でコミットハッシュが変わったケースもgit cherryの等価パッチ検出で
    # カバーするよう堅牢化した(cleanup_git_resources.py側)。このトリガー自身の
    # --dry-runとは独立して、環境変数DRY_RUN=trueを設定するだけでも
    # cleanup_merged_git_resources()単体を検証実行(実際の削除なし)できる。
    # 【instructions/186】dry-run以外での失敗(gitコマンド欠落等のインフラ不備を含む)は
    # Fail-Closedとして即座にサイクルを中断し、Exit 1で後続の閾値判定・VMキックへ処理を
    # 進めない(以前はここで例外を握り潰し、閾値判定を継続させるFail-Openだった)。
    if not args.dry_run:
        try:
            cleanup_merged_git_resources()
        except Exception as e:  # noqa: BLE001 - Fail-Closed: 検知した例外はログ後に
            # 即座にサイクルを中断するための捕捉(握り潰しではない)。
            message = f"Gitリソースクリーンアップに失敗したため、このサイクルを中断します: {e}"
            print(f"🛑  [Trigger] {message}", file=sys.stderr)
            _save_last_run_status("error", message)
            return 1

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
    # 検証用ログ(run/shadow_mode_log.jsonl)へ記録する。
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
            "抑止しました(判定結果はrun/shadow_mode_log.jsonlへ記録済み)。",
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

    # 【instructions/298: Graceful Shutdown】シグナル受信によりこのサイクルが中断
    # された場合、通常の"error"/"triggered"分類とは区別して報告する(claimは
    # _try_claim_and_kickの既存ロジックにより既に解放済みのため、冪等性は保たれている)。
    if _shutdown_requested:
        message = (
            "Graceful Shutdown要求(SIGTERM/SIGINT)を受信したため、このサイクルを"
            "中断しました。claim済みだった対象は解放済みです(instructions/298)。"
        )
        _save_last_run_status("interrupted", message)
        return 130

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

    # 【🛑 RETIRED 2026-08-13】ここで即座に安全側へ抜ける。以降の閾値評価・Git
    # クリーンアップ・DBのtrigger_state claim・エフェメラルVMキックは一切行わない
    # (ユーザー承認済み: 抽出ロジックの復元ではなくトリガー自体の退役を選択)。
    retirement_message = (
        "tools/mlops_trigger.py は退役済みです(2026-08-13)。前提だった"
        "tools/extract_dataset.py が commit b2b22d9 で削除されて以降、抽出ロジックが"
        "存在しないため、閾値評価もエフェメラルVMキックも行わず何もせず終了します。"
    )
    print(f"🛑 [Trigger] {retirement_message}", file=sys.stderr)
    if not args.dry_run:
        _save_last_run_status("retired", retirement_message)
    return 0


if __name__ == "__main__":
    sys.exit(main())

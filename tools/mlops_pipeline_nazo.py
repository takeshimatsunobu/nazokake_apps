"""
tools/mlops_pipeline_nazo.py
===============================
なぞかけ生成モデルのMLOps完全自動パイプライン(Epic 3)。

以下を直列実行する:
  1. Pre-flight GPU Cleanup: 前回の異常終了で残ったゾンビプロセスを掃除する。
  2. VRAMグローバルロックの取得: アプリ本体(apps/evaluator/backend)や
     tools/mlops_pipeline_agent.py が使用中の場合は、指数的バックオフで
     ポーリング待機してから取得する(限られたVRAM 8GBの排他制御)。
  3. データ抽出: tools/extract_dataset.py(SFT/DPOデータセット)をサブプロセスで実行する。
  4. 学習(instructions/280: SFT->DPO直列パイプライン):
     4a. tools/train_nazo_sft_model.py(事前学習: SFT、tools/extract_dataset.pyの
         data/sft_dataset.jsonlを使用)
     4b. tools/train_nazo_model.py(選好最適化: DPO、data/dpo_dataset.jsonlを使用)
     いずれも内部で共用コアエンジンtools/train_unsloth_core.pyを呼び出す
     (instructions/274)。このプロセス自身が既にVRAMロックを保持したまま両ステップを
     直列実行するため、GPUの同時競合(OOM)は発生しない。
  5. 自動評価(定量ゲート、instructions/280): tools/evaluate_model.py が実推論で
     Format Adherence Rateを測り、ベースラインとの比較・合否判定・ベースライン更新まで
     自己完結して行い、合否を自身の終了コード(0=合格/1=不合格)で通知する
     (mlops_common.run_step()が非0終了コードを検知しPipelineExecutionErrorとして
     伝播させるため、ここでの合否の再判定は行わない。同一baseline_metrics_nazo.jsonを
     このプロセス側でも二重に読み書きすると、「今回の値」を「今回の値」と比較して
     常にdelta=0になるゲート形骸化バグを生むため、判定責務はevaluate_model.py側に
     完全に一本化してある)。

旧 tools/mlops_pipeline.py は、なぞかけ生成モデルを学習しながらNazo-Agentの
AST自己修復ベンチマーク(tools/benchmark/run_benchmark.py)で評価するという、
学習対象と評価対象が食い違ったパイプラインだった。この分離により、なぞかけ生成の
品質はなぞかけ生成モデル自身の実推論評価(tools/evaluate_model.py)で正しく評価する。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# `uv run python tools/mlops_pipeline_nazo.py` のように直接実行すると sys.path[0] は
# tools/ 自身になり、`from tools import mlops_common`(リポジトリ直下のパッケージとして
# 参照する絶対import)が ModuleNotFoundError: No module named 'tools' になる。
# tools/benchmark/run_benchmark.pyと同じ対処(リポジトリルートを明示的にsys.pathへ追加)。
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from nazokake_core.database import async_release_trigger_slot  # noqa: E402
from tools import export_metrics  # noqa: E402
from tools import mlops_common  # noqa: E402
from tools import mlops_experiments_db  # noqa: E402
from tools.exceptions import MLOpsInfrastructureError, PipelineExecutionError  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
EVALUATION_REPORT_PATH = BASE_DIR / "run" / "audit_reports" / "evaluation_report.json"
EXTRACTION_STATS_PATH = BASE_DIR / "data" / "extraction_stats.json"
BASE_MODEL = "elyza:8b"


def _record_experiment(report: dict | None, latency: float, *, pipeline_success: bool) -> None:
    """今回のパイプライン実行結果を実験管理DB(mlops_experiments.db)へ不変ログとして
    記録する。評価が完了しなかった場合(report=None)もsuccess_rate=Noneとして
    記録し、「実行したが評価不能だった」という事実自体を欠落させない。

    あわせて、tools/mlops_trigger.pyが奪取したtrigger_state(pipeline_id="nazo")の
    claimを解放する(instructions/174追補: 排他制御(Mutex)とクールダウン
    (実行間隔制御)の分離)。pipeline_success=Trueの場合のみ
    status="success"+last_completed_at=NOWを記録してクールダウンを開始させる。
    Falseの場合はstatus="failed"のみを記録し、last_completed_atは更新しない
    (=次回トリガー時に即時リトライ可能な状態のままにする)。
    """
    extraction_stats = None
    if EXTRACTION_STATS_PATH.exists():
        extraction_stats = json.loads(EXTRACTION_STATS_PATH.read_text(encoding="utf-8"))

    format_adherence_rate = None
    if report is not None and report.get("status") == "completed":
        format_adherence_rate = report.get("metrics", {}).get("format_adherence_rate")

    mlops_experiments_db.record_experiment(
        pipeline_type="nazo",
        dataset_size=(extraction_stats or {}).get("dataset_size"),
        coreset_ratio=(extraction_stats or {}).get("coreset_ratio"),
        base_model=BASE_MODEL,
        success_rate=format_adherence_rate,
        latency=latency,
        regression_rate=None,  # なぞかけ生成モデルの評価にはRegression Rateの概念が無い
    )
    print("📝 [実験ログ] mlops_experiments.dbへ記録しました。")

    metrics_path = export_metrics.export_metrics()
    print(f"📊 [ダッシュボード] 静的JSONをアトミックに更新しました: {metrics_path}")

    asyncio.run(async_release_trigger_slot("nazo", success=pipeline_success))
    print(
        f"🔓 [トリガー状態] trigger_state(nazo)を"
        f"{'success' if pipeline_success else 'failed'}へ更新しました。"
    )


def main() -> int:
    start_time = time.monotonic()

    mlops_common.preflight_gpu_cleanup()

    lock = mlops_common.acquire_vram_lock_with_backoff()
    # 【instructions/275、instructions/280でSFT/DPO両ステップに適用】このプロセスは
    # 既にVRAMロックを保持している。学習サブプロセス(tools/train_nazo_sft_model.py・
    # tools/train_nazo_model.pyの両方)が自身でも取得を試みて自己デッドロックに
    # 陥らないよう、既に保持済みであることを子プロセスへ伝える(env=Noneの
    # subprocess.Popenは既定でこの環境変数をそのまま継承する)。
    os.environ[mlops_common.VRAM_LOCK_HELD_BY_PARENT_ENV] = "1"
    try:
        try:
            mlops_common.run_step(
                "データ抽出(なぞかけSFT/DPOデータセット)",
                ["uv", "run", "python", "tools/extract_dataset.py"],
            )

            mlops_common.run_step(
                "学習(なぞかけ生成モデル: SFT事前学習)",
                ["uv", "run", "python", "tools/train_nazo_sft_model.py"],
            )

            mlops_common.run_step(
                "学習(なぞかけ生成モデル: DPO選好最適化)",
                ["uv", "run", "python", "tools/train_nazo_model.py"],
            )

            mlops_common.run_step(
                "自動評価(なぞかけ生成モデルのFormat Adherence Rateゲート)",
                ["uv", "run", "python", "tools/evaluate_model.py"],
            )
        finally:
            lock.release()
            print("🔓 [VRAM排他制御] VRAMロックを解放しました。")
    except MLOpsInfrastructureError as e:
        # Docker不在等、インフラ起因でステップが異常終了した場合(instructions/136で
        # run_benchmark.pyがreturncode=125として送出する信号がrun_step()経由でここまで
        # 伝播する)。監視システムが区別できるよう、終了コードも125に揃える。
        latency = time.monotonic() - start_time
        print(f"🚨 [Infra-Fail] インフラエラーによりパイプラインを停止します: {e}")
        _record_experiment(None, latency, pipeline_success=False)
        return 125
    except PipelineExecutionError as e:
        # サブプロセス自体のロジック的なクラッシュ(インフラエラー以外)。以前は
        # run_step()内のsys.exit(1)でプロセスごと即死しており、実験管理DBへの記録
        # (_record_experiment)もダッシュボード用静的JSON(export_metrics)の更新も
        # 一切実行されないサイレントな障害だった(instructions/134で検出)。
        latency = time.monotonic() - start_time
        print(f"🚨 [Fail-Fast] ステップ異常終了によりパイプラインを停止します: {e}")
        _record_experiment(None, latency, pipeline_success=False)
        return 1
    except Exception as e:  # noqa: BLE001 - 予期しない失敗も必ず記録してから終了する
        latency = time.monotonic() - start_time
        print(f"🚨 [Fail-Fast] 予期しないエラーによりパイプラインを停止します: {e}")
        _record_experiment(None, latency, pipeline_success=False)
        return 1

    # ここに到達するのは、評価ステップ(tools/evaluate_model.py)を含む全ステップが
    # 例外を送出せず終了した場合のみ = 同スクリプト自身のゲート判定(instructions/280)
    # で既に合格していることを意味する(不合格ならexit 1 -> run_step()が
    # PipelineExecutionErrorを送出し、上のexceptブロックで既にpipeline_success=False
    # として処理・returnされている)。ここでの合否再判定は行わない。
    latency = time.monotonic() - start_time

    if not EVALUATION_REPORT_PATH.exists():
        message = "🚨 [Fail-Fast] 評価レポートが見つかりませんでした。"
        print(message)
        mlops_common.send_alert_webhook(f"[MLOps/nazo] {message}")
        _record_experiment(None, latency, pipeline_success=False)
        return 1

    report = json.loads(EVALUATION_REPORT_PATH.read_text(encoding="utf-8"))
    _record_experiment(report, latency, pipeline_success=True)
    print("\n🎉 学習成功およびデプロイ承認(なぞかけ生成モデル)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

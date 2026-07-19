"""
tools/mlops_pipeline_agent.py
================================
Nazo-Agent(自己修復エンジン)のMLOps完全自動パイプライン(Epic 3)。

以下を直列実行する:
  1. Pre-flight GPU Cleanup: 前回の異常終了で残ったゾンビプロセスを掃除する。
  2. VRAMグローバルロックの取得: アプリ本体(apps/evaluator/backend)や
     tools/mlops_pipeline_nazo.py が使用中の場合は、指数的バックオフで
     ポーリング待機してから取得する(限られたVRAM 8GBの排他制御)。
  3. データ抽出: tools/extract_agent_sft.py(推論軌跡のChatML化)をサブプロセスで実行する。
     このステップは失敗を許容する(tolerate_failure)。抽出元(error_log.txt等)は
     tools/nazo_agent.py が自己修復に成功した直後にそのつど生成する一時ファイルであり、
     このパイプラインの実行タイミングでは既に消費・消失済みであることが多いため
     (実際の蓄積は成功修復のたびにnazo_agent.py自身が既に行っている、この
     ステップは取りこぼしを拾うベストエフォート)。
  4. 学習: tools/train_unsloth.py をサブプロセスで実行する。
  5. 自動評価(定量ゲート): tools/benchmark/run_benchmark.py を実行してメトリクスJSONを
     取得し、Success Rate Delta>=0 かつ Code Complexity増加率<10% を満たした場合のみ
     「学習成功およびデプロイ承認」として正常終了する。

旧 tools/mlops_pipeline.py の評価ロジック(Success Rate Delta / Code Complexity判定)を
そのまま継承している。tools/benchmark/run_benchmark.pyはNazo-Agentの自己修復能力を
測るベンチマークであり、このパイプライン(Nazo-Agent自身の学習)にとっては
正しい評価対象である(旧パイプラインでの誤りは、これをなぞかけ生成モデルの
評価にも使い回していた点)。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from statistics import mean

# `uv run python tools/mlops_pipeline_agent.py` のように直接実行すると sys.path[0] は
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
from tools.config import settings  # noqa: E402
from tools.exceptions import MLOpsInfrastructureError, PipelineExecutionError  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BENCHMARK_REPORTS_DIR = BASE_DIR / "tools" / "benchmark" / "reports"
BASELINE_PATH = BENCHMARK_REPORTS_DIR / "baseline_metrics_agent.json"
AGENT_SFT_PATH = BASE_DIR / "tools" / "dataset" / "agent_sft.jsonl"
BASE_MODEL = "qwen2.5-coder:7b"


def _find_latest_benchmark_report() -> Path | None:
    reports = sorted(BENCHMARK_REPORTS_DIR.glob("benchmark_*.json"))
    return reports[-1] if reports else None


def _average_complexity_growth_rate(results: list[dict]) -> float | None:
    """各fixtureのASTノード数増減率の平均を返す(元のノード数を計算できたfixtureのみ対象)。"""
    rates = []
    for r in results:
        complexity = r.get("code_complexity") or {}
        original = complexity.get("original")
        delta = complexity.get("node_count_delta")
        if not original or delta is None or not original.get("node_count"):
            continue
        rates.append(delta / original["node_count"])
    return mean(rates) if rates else None


def _load_baseline() -> dict | None:
    if not BASELINE_PATH.exists():
        return None
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _save_baseline(metrics: dict) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def evaluate_quality_gate(report: dict) -> bool:
    """定量評価ゲート: Success Rate Delta>=0 かつ Code Complexity増加率<10% を判定する。

    Success Rateが計測不能(None、例: ベンチマークのDocker実行環境が無い等)な場合は、
    非退行を確認できないため安全側に倒して不合格とする。
    """
    aggregate = report.get("aggregate", {})
    success_rate = aggregate.get("success_rate")
    complexity_growth_rate = _average_complexity_growth_rate(report.get("results", []))

    baseline = _load_baseline()
    baseline_success_rate = baseline.get("success_rate") if baseline else None

    print(f"📊 Success Rate: {success_rate} (ベースライン: {baseline_success_rate})")
    print(f"📊 Code Complexity 増加率(平均): {complexity_growth_rate}")

    if success_rate is None:
        print(
            "🚨 [ゲート判定] Success Rateを計測できませんでした"
            "(例: ベンチマークのDocker実行環境が無い)。非退行を確認できないため、"
            "安全側に倒して不合格とします。"
        )
        return False

    if baseline_success_rate is None:
        print(
            "ℹ️  ベースラインが存在しないため、Success Rate Deltaの判定はスキップします。"
        )
    else:
        success_rate_delta = success_rate - baseline_success_rate
        print(f"📊 Success Rate Delta: {success_rate_delta}")
        if success_rate_delta < 0:
            print("🚨 [ゲート判定] Success Rateが現行ベースラインを下回りました。")
            return False

    if (
        complexity_growth_rate is not None
        and complexity_growth_rate >= settings.quality_gate_complexity_max
    ):
        print(
            f"🚨 [ゲート判定] Code Complexity増加率が上限"
            f"({settings.quality_gate_complexity_max:.0%})を超えました。"
        )
        return False

    _save_baseline(
        {"success_rate": success_rate, "complexity_growth_rate": complexity_growth_rate}
    )
    return True


def _count_agent_sft_records() -> int | None:
    if not AGENT_SFT_PATH.exists():
        return None
    with AGENT_SFT_PATH.open(encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _record_experiment(report: dict | None, latency: float, *, pipeline_success: bool) -> None:
    """今回のパイプライン実行結果を実験管理DB(mlops_experiments.db)へ不変ログとして
    記録する。評価が完了しなかった場合(report=None)もsuccess_rate=Noneとして
    記録し、「実行したが評価不能だった」という事実自体を欠落させない。

    dataset_sizeはtools/dataset/agent_sft.jsonlの累積行数(このパイプラインでは
    tools/extract_dataset.pyのようなコアーセット・リプレイの層化抽出を行わないため、
    coreset_ratioは常にNone)。

    あわせて、tools/mlops_trigger.pyが奪取したtrigger_state(pipeline_id="agent")の
    claimを解放する(instructions/174追補: 排他制御(Mutex)とクールダウン
    (実行間隔制御)の分離)。pipeline_success=Trueの場合のみ
    status="success"+last_completed_at=NOWを記録してクールダウンを開始させる。
    Falseの場合はstatus="failed"のみを記録し、last_completed_atは更新しない
    (=次回トリガー時に即時リトライ可能な状態のままにする)。
    """
    aggregate = (report or {}).get("aggregate", {})
    complexity_growth_rate = None
    if report is not None:
        complexity_growth_rate = _average_complexity_growth_rate(
            report.get("results", [])
        )

    mlops_experiments_db.record_experiment(
        pipeline_type="agent",
        dataset_size=_count_agent_sft_records(),
        coreset_ratio=None,
        base_model=BASE_MODEL,
        success_rate=aggregate.get("success_rate"),
        latency=latency,
        regression_rate=aggregate.get("avg_regression_rate"),
    )
    print("📝 [実験ログ] mlops_experiments.dbへ記録しました。")
    if complexity_growth_rate is not None:
        print(f"   (参考) Code Complexity 増加率(平均): {complexity_growth_rate}")

    metrics_path = export_metrics.export_metrics()
    print(f"📊 [ダッシュボード] 静的JSONをアトミックに更新しました: {metrics_path}")

    asyncio.run(async_release_trigger_slot("agent", success=pipeline_success))
    print(
        f"🔓 [トリガー状態] trigger_state(agent)を"
        f"{'success' if pipeline_success else 'failed'}へ更新しました。"
    )


def main() -> int:
    start_time = time.monotonic()

    mlops_common.preflight_gpu_cleanup()

    lock = mlops_common.acquire_vram_lock_with_backoff()
    try:
        try:
            mlops_common.run_step(
                "データ抽出(Nazo-Agent推論軌跡)",
                ["uv", "run", "python", "tools/extract_agent_sft.py"],
                tolerate_failure=True,
            )

            mlops_common.run_step(
                "学習(Nazo-Agent)",
                ["uv", "run", "python", "tools/train_unsloth.py"],
            )

            mlops_common.run_step(
                "自動評価(定量ゲート用ベンチマーク)",
                ["uv", "run", "python", "tools/benchmark/run_benchmark.py"],
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

    latency = time.monotonic() - start_time

    report_path = _find_latest_benchmark_report()
    if report_path is None:
        message = "🚨 [Fail-Fast] ベンチマークレポートが見つかりませんでした。"
        print(message)
        mlops_common.send_alert_webhook(f"[MLOps/agent] {message}")
        _record_experiment(None, latency, pipeline_success=False)
        return 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    gate_passed = evaluate_quality_gate(report)
    _record_experiment(report, latency, pipeline_success=gate_passed)

    if gate_passed:
        print("\n🎉 学習成功およびデプロイ承認(Nazo-Agent)")
        return 0

    message = "🛑 定量評価ゲートを通過しなかったため、デプロイを承認しません。"
    print(f"\n{message}")
    mlops_common.send_alert_webhook(f"[MLOps/agent] {message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

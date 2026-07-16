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
  4. 学習: tools/train_unsloth.py をサブプロセスで実行する。
  5. 自動評価(定量ゲート): tools/evaluate_model.py でホールドアウト正解率を計測し、
     ベースラインを下回っていない場合のみ「学習成功およびデプロイ承認」とする。

旧 tools/mlops_pipeline.py は、なぞかけ生成モデルを学習しながらNazo-Agentの
AST自己修復ベンチマーク(tools/benchmark/run_benchmark.py)で評価するという、
学習対象と評価対象が食い違ったパイプラインだった。この分離により、なぞかけ生成の
品質はなぞかけ生成モデル自身のホールドアウト正解率(tools/evaluate_model.py)で
正しく評価する。
"""

from __future__ import annotations

import json
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

from tools import mlops_common  # noqa: E402
from tools import mlops_experiments_db  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
EVALUATION_REPORT_PATH = BASE_DIR / "tools" / "audit_reports" / "evaluation_report.json"
BASELINE_PATH = BASE_DIR / "tools" / "audit_reports" / "baseline_metrics_nazo.json"
EXTRACTION_STATS_PATH = BASE_DIR / "data" / "extraction_stats.json"
BASE_MODEL = "elyza:8b"


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
    """定量評価ゲート: ホールドアウト正解率が既存ベースラインを下回っていないかを判定する。

    report["status"] が "completed" でない場合(アダプタ未検出/テストデータ無し等)は、
    正解率そのものを計測できていないため、非退行を確認できず安全側に倒して不合格とする。
    """
    if report.get("status") != "completed":
        print(
            f"🚨 [ゲート判定] 評価が完了しませんでした(status={report.get('status')}, "
            f"reason={report.get('reason')})。非退行を確認できないため、"
            "安全側に倒して不合格とします。"
        )
        return False

    accuracy = report.get("metrics", {}).get("accuracy")
    baseline = _load_baseline()
    baseline_accuracy = baseline.get("accuracy") if baseline else None

    print(f"📊 Accuracy: {accuracy} (ベースライン: {baseline_accuracy})")

    if baseline_accuracy is None:
        print("ℹ️  ベースラインが存在しないため、Accuracy Deltaの判定はスキップします。")
    else:
        delta = accuracy - baseline_accuracy
        print(f"📊 Accuracy Delta: {delta}")
        if delta < 0:
            print("🚨 [ゲート判定] Accuracyが現行ベースラインを下回りました。")
            return False

    _save_baseline({"accuracy": accuracy})
    return True


def _record_experiment(report: dict | None, latency: float) -> None:
    """今回のパイプライン実行結果を実験管理DB(mlops_experiments.db)へ不変ログとして
    記録する。評価が完了しなかった場合(report=None)もsuccess_rate=Noneとして
    記録し、「実行したが評価不能だった」という事実自体を欠落させない。
    """
    extraction_stats = None
    if EXTRACTION_STATS_PATH.exists():
        extraction_stats = json.loads(EXTRACTION_STATS_PATH.read_text(encoding="utf-8"))

    accuracy = None
    if report is not None and report.get("status") == "completed":
        accuracy = report.get("metrics", {}).get("accuracy")

    mlops_experiments_db.record_experiment(
        pipeline_type="nazo",
        dataset_size=(extraction_stats or {}).get("dataset_size"),
        coreset_ratio=(extraction_stats or {}).get("coreset_ratio"),
        base_model=BASE_MODEL,
        success_rate=accuracy,
        latency=latency,
        regression_rate=None,  # なぞかけ生成モデルの評価にはRegression Rateの概念が無い
    )
    print("📝 [実験ログ] mlops_experiments.dbへ記録しました。")

    metrics_path = mlops_experiments_db.export_metrics_to_json()
    print(f"📊 [ダッシュボード] 静的JSONを更新しました: {metrics_path}")


def main() -> int:
    start_time = time.monotonic()

    mlops_common.preflight_gpu_cleanup()

    lock = mlops_common.acquire_vram_lock_with_backoff()
    try:
        mlops_common.run_step(
            "データ抽出(なぞかけSFT/DPOデータセット)",
            ["uv", "run", "python", "tools/extract_dataset.py"],
        )

        mlops_common.run_step(
            "学習(なぞかけ生成モデル)",
            ["uv", "run", "python", "tools/train_unsloth.py"],
        )

        mlops_common.run_step(
            "自動評価(なぞかけ生成モデルのホールドアウト検証)",
            ["uv", "run", "python", "tools/evaluate_model.py"],
        )
    finally:
        lock.release()
        print("🔓 [VRAM排他制御] VRAMロックを解放しました。")

    latency = time.monotonic() - start_time

    if not EVALUATION_REPORT_PATH.exists():
        print("🚨 [Fail-Fast] 評価レポートが見つかりませんでした。")
        _record_experiment(None, latency)
        return 1

    report = json.loads(EVALUATION_REPORT_PATH.read_text(encoding="utf-8"))
    gate_passed = evaluate_quality_gate(report)
    _record_experiment(report, latency)

    if gate_passed:
        print("\n🎉 学習成功およびデプロイ承認(なぞかけ生成モデル)")
        return 0

    print("\n🛑 定量評価ゲートを通過しなかったため、デプロイを承認しません。")
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""
tools/mlops_pipeline.py
=========================
MLOps完全自動パイプライン(Epic 3)。

以下を直列実行する:
  1. Pre-flight GPU Cleanup: nvidia-smiでVRAMを占有中のPIDを取得し、自身以外の
     不要なPythonプロセスをtaskkillで強制終了する。
  2. データ抽出: tools/extract_dataset.py をサブプロセスで実行する。
  3. 学習: tools/train_unsloth.py を、自身のPIDを--ppidとして渡してサブプロセスで
     実行する(Child Suicide機構による異常終了時のVRAM解放を成立させるため)。
  4. 自動評価(定量ゲート): tools/benchmark/run_benchmark.py を実行してメトリクスJSONを
     取得し、Success Rate Delta>=0 かつ Code Complexity増加率<10% を満たした場合のみ
     「学習成功およびデプロイ承認」として正常終了する。

いずれかのステップが失敗した時点で即座にパイプライン全体を異常終了させる
フェイルファスト構成。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from statistics import mean

import psutil

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
BENCHMARK_REPORTS_DIR = BASE_DIR / "tools" / "benchmark" / "reports"
BASELINE_METRICS_PATH = BENCHMARK_REPORTS_DIR / "baseline_metrics.json"

# nvidia-smiのPIDが「不要なPythonプロセス」かどうかの判定に使う部分一致キーワード。
# tools/safe_reset_infra.py の LOCK_CANDIDATE_NAME_KEYWORDS と同じ考え方: 無差別に
# システムプロセス全体を対象にせず、明らかに学習/推論用途のPythonプロセスだけに絞る
# (Ollama等の正当なGPU利用プロセスを誤って殺さないため)。
UNWANTED_PROCESS_NAME_KEYWORDS = ("python", "uvicorn")

MAX_COMPLEXITY_GROWTH_RATE = 0.10  # 10%


def preflight_gpu_cleanup() -> list[int]:
    """nvidia-smiでVRAM占有中のPIDを取得し、自身以外の不要なPythonプロセスを
    taskkill /F で強制終了する。戻り値は実際に終了させたPIDのリスト。
    """
    print("\n🧹 [Step 0] Pre-flight GPU Cleanup を実行します...")
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except FileNotFoundError:
        print("⚠️  nvidia-smiが見つかりません。GPUクリーンアップをスキップします。")
        return []
    except subprocess.TimeoutExpired:
        print(
            "⚠️  nvidia-smiがタイムアウトしました。GPUクリーンアップをスキップします。"
        )
        return []

    if result.returncode != 0:
        print(
            f"⚠️  nvidia-smiの実行に失敗しました(code={result.returncode})。"
            "GPUクリーンアップをスキップします。"
        )
        return []

    pids: list[int] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "Insufficient Permissions" in line:
            continue
        try:
            pids.append(int(line.split(",")[0].strip()))
        except ValueError:
            continue

    self_pid = os.getpid()
    killed: list[int] = []
    for pid in pids:
        if pid == self_pid:
            continue
        try:
            name = (psutil.Process(pid).name() or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if not any(keyword in name for keyword in UNWANTED_PROCESS_NAME_KEYWORDS):
            continue

        print(
            f"   🔥 VRAM占有中の不要なPythonプロセスを検知: PID={pid} ({name}) -> taskkill"
        )
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        killed.append(pid)

    if not killed:
        print("   ✅ 不要なプロセスは検出されませんでした。")
    return killed


def run_step(step_name: str, cmd: list[str]) -> None:
    """1ステップをBASE_DIR起点で同期実行する。失敗時は即座にsys.exit(1)する。"""
    print(f"\n🔍 [Step] {step_name} を実行します... ({' '.join(cmd)})")
    # encodingを明示しない場合、Windowsの既定コンソールコードページ(cp932)で
    # 子プロセスのUTF-8出力(絵文字等)を読もうとしてUnicodeDecodeErrorが発生し、
    # そのステップの出力が読み取れなくなる(プロセス自体は継続するため気付きにくい)。
    result = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")

    if result.returncode != 0:
        print(
            f"🚨 [Fail-Fast] {step_name} が異常終了しました "
            f"(code={result.returncode})。パイプラインを停止します。"
        )
        sys.exit(1)

    print(f"✅ {step_name} が完了しました。")


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
    if not BASELINE_METRICS_PATH.exists():
        return None
    return json.loads(BASELINE_METRICS_PATH.read_text(encoding="utf-8"))


def _save_baseline(metrics: dict) -> None:
    BASELINE_METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_METRICS_PATH.write_text(
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
        and complexity_growth_rate >= MAX_COMPLEXITY_GROWTH_RATE
    ):
        print(
            f"🚨 [ゲート判定] Code Complexity増加率が上限"
            f"({MAX_COMPLEXITY_GROWTH_RATE:.0%})を超えました。"
        )
        return False

    _save_baseline(
        {"success_rate": success_rate, "complexity_growth_rate": complexity_growth_rate}
    )
    return True


def main() -> int:
    preflight_gpu_cleanup()

    run_step(
        "データ抽出(SFT/DPOデータセット)",
        ["uv", "run", "python", "tools/extract_dataset.py"],
    )

    run_step(
        "学習(Child Suicide機構つき)",
        ["uv", "run", "python", "tools/train_unsloth.py", "--ppid", str(os.getpid())],
    )

    run_step(
        "自動評価(定量ゲート用ベンチマーク)",
        ["uv", "run", "python", "tools/benchmark/run_benchmark.py"],
    )

    report_path = _find_latest_benchmark_report()
    if report_path is None:
        print("🚨 [Fail-Fast] ベンチマークレポートが見つかりませんでした。")
        return 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    if evaluate_quality_gate(report):
        print("\n🎉 学習成功およびデプロイ承認")
        return 0

    print("\n🛑 定量評価ゲートを通過しなかったため、デプロイを承認しません。")
    return 1


if __name__ == "__main__":
    sys.exit(main())

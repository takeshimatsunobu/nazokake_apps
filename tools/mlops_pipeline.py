"""
tools/mlops_pipeline.py
=========================
MLOps完全自動パイプライン(Epic 3)。

以下を直列実行する:
  1. Pre-flight GPU Cleanup: nvidia-smiでVRAMを占有中のPIDを取得し、自身以外の
     不要なPythonプロセスをtaskkillで強制終了する。
  2. データ抽出: tools/extract_dataset.py をサブプロセスで実行する。
  3. 学習: tools/train_unsloth.py をサブプロセスで実行する。
  4. 自動評価(定量ゲート): tools/benchmark/run_benchmark.py を実行してメトリクスJSONを
     取得し、Success Rate Delta>=0 かつ Code Complexity増加率<10% を満たした場合のみ
     「学習成功およびデプロイ承認」として正常終了する。

データ抽出/学習/自動評価の各サブプロセスは tools/process_manager.py 経由で起動する。
以前は各スクリプト側が--ppidを受け取りポーリングで親の死活を監視して自爆する
「Child Suicide」機構を持っていたが、検知遅延や実装の不確実性があったため廃止した。
プロセスツリー(サブプロセスとその子孫)のアトミックな破棄は、このオーケストレーター側が
OSネイティブな機構(POSIXのプロセスグループ/WindowsのJob Object)で保証する。

いずれかのステップが失敗した時点で即座にパイプライン全体を異常終了させる
フェイルファスト構成。
"""

from __future__ import annotations

import json
import locale
import os
import subprocess
import sys
from pathlib import Path
from statistics import mean

import psutil

import process_manager

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


def _decode_native_output(data: bytes) -> str:
    """ネイティブコマンドの出力バイト列を安全にデコードする。

    まずUTF-8(errors="strict")でのデコードを試みる(run_native_command()が
    PYTHONIOENCODING=utf-8を子プロセスへプロアクティブに要求しているため、多くの
    場合はこれで成功する)。UTF-8として不正なバイト列だった場合のみ、
    locale.getpreferredencoding(False)(システムの現在のロケール設定)を用いた
    動的フォールバックデコードへ切り替える。特定のコードページ(例: "mbcs")を
    ハードコードしないことで、実行環境のロケールに関わらず追従できる。
    """
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        fallback_encoding = locale.getpreferredencoding(False)
        return data.decode(fallback_encoding, errors="strict")


def run_native_command(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Windowsネイティブコマンド(nvidia-smi, taskkill等)との境界防衛
    (Anti-Corruption Layer)。

    子プロセスの環境変数にPYTHONIOENCODING=utf-8を強制し、UTF-8出力をプロアクティブに
    要求する(ネイティブコマンド自体はPython製ではないため必ずしも従うわけではないが、
    Python製の子プロセスやラッパー経由で呼ばれる場合に効く)。出力はバイト列のまま
    受け取り、_decode_native_output()の「UTF-8優先・失敗時のみロケールへ動的フォール
    バック」というデコード戦略に委ねる(特定のコードページのハードコードを排除する)。
    """
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(cmd, capture_output=True, env=env, **kwargs)
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=_decode_native_output(result.stdout) if result.stdout else "",
        stderr=_decode_native_output(result.stderr) if result.stderr else "",
    )


def preflight_gpu_cleanup() -> list[int]:
    """nvidia-smiでVRAM占有中のPIDを取得し、自身以外の不要なPythonプロセスを
    taskkill /F で強制終了する。戻り値は実際に終了させたPIDのリスト。
    """
    print("\n🧹 [Step 0] Pre-flight GPU Cleanup を実行します...")
    try:
        result = run_native_command(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
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
        run_native_command(["taskkill", "/PID", str(pid), "/F"])
        killed.append(pid)

    if not killed:
        print("   ✅ 不要なプロセスは検出されませんでした。")
    return killed


def run_step(step_name: str, cmd: list[str]) -> None:
    """1ステップをBASE_DIR起点で同期実行する。失敗時は即座にsys.exit(1)する。

    tools/process_manager.ManagedProcess経由で起動することで、このステップ自身が
    正常終了した後でも、その子孫プロセスに生き残りが無いことをOSネイティブな
    機構(POSIXのプロセスグループ/WindowsのJob Object)で保証する(VRAMリークの
    原因となるゾンビ子孫プロセスの排除)。

    このcmdは"uv run python tools/..."であり、呼び出し先のPythonスクリプト自身が
    sys.stdout.reconfigure(encoding="utf-8")で出力エンコーディングをUTF-8に固定して
    いる(ネイティブWindowsコマンドではない)ため、encoding="utf-8"で受け取る。
    errors="strict"により、想定外のバイト列が万一混入した場合は即座に例外として
    検出する(errors="replace"による文字化けのサイレント黒箱化は行わない)。
    """
    print(f"\n🔍 [Step] {step_name} を実行します... ({' '.join(cmd)})")
    with process_manager.ManagedProcess(cmd, cwd=str(BASE_DIR)) as proc:
        stdout, stderr = proc.communicate()
        returncode = proc.returncode

    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="")

    if returncode != 0:
        print(
            f"🚨 [Fail-Fast] {step_name} が異常終了しました "
            f"(code={returncode})。パイプラインを停止します。"
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
        "学習",
        ["uv", "run", "python", "tools/train_unsloth.py"],
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

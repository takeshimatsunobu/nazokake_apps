"""
tools/mlops_pipeline.py
=========================
MLOpsオーケストレーターの基礎(Epic 3 Phase 1)。

独立して存在するデータ抽出スクリプト群を、決まった順番で直列に実行する。
いずれかのステップが失敗した時点で即座にパイプライン全体を異常終了させる
フェイルファスト構成。
"""

import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent

PIPELINE_STEPS = [
    ("Nazo-Agent推論軌跡SFTデータ抽出", ["uv", "run", "python", "tools/extract_agent_sft.py"]),
    (
        "アプリ本体SFTデータ抽出",
        ["uv", "run", "python", "apps/evaluator/backend/scripts/extract_sft_data.py"],
    ),
    (
        "アプリ本体DPOデータ抽出",
        ["uv", "run", "python", "apps/evaluator/backend/scripts/extract_dpo_data.py"],
    ),
    ("学習済みモデルのホールドアウト評価", ["uv", "run", "python", "tools/evaluate_model.py"]),
]


def run_step(step_name: str, cmd: list[str]) -> None:
    """1ステップをBASE_DIR起点で同期実行する。失敗時は即座にsys.exit(1)する。"""
    print(f"\n🔍 [Step] {step_name} を実行します... ({' '.join(cmd)})")
    result = subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True)

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")

    if result.returncode != 0:
        print(f"🚨 [Fail-Fast] {step_name} が異常終了しました (code={result.returncode})。パイプラインを停止します。")
        sys.exit(1)

    print(f"✅ {step_name} が完了しました。")


def main() -> None:
    for step_name, cmd in PIPELINE_STEPS:
        run_step(step_name, cmd)

    print("\n✅ Phase 1: データ抽出パイプラインが正常に完了しました")


if __name__ == "__main__":
    main()

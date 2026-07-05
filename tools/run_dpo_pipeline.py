"""
run_dpo_pipeline.py
====================
Phase 4.12b: DPOデータ抽出 -> batch_factory側の学習準備(ドライラン)までを
一気通貫で実行するLv.3パイプライン・オーケストレーター。

【安全設計】既定では実際のGPU学習は一切起動しない。batch_factory側は必ず
--dry-run 付きで起動し、データ件数を標準出力に表示した時点で安全に停止する。
実学習を回すには --run-training を明示的に指定する必要がある。

各ステップはサブプロセスとして、対応するアプリ自身の venv (apps/evaluator/.venv_ai,
apps/batch_factory/.venv_train) と作業ディレクトリで実行する。これは
extract_dpo_data.py / train_dpo.py が Path.cwd() 相対のパス解決(serviceAccountKey.json
や data/ の位置)に依存しており、他のcwdから直接importして呼び出すと解決が壊れるため。

使い方:
    python tools/run_dpo_pipeline.py                # 抽出 + 学習準備(ドライラン)
    python tools/run_dpo_pipeline.py --run-training  # 抽出 + 実学習(GPU使用、注意)
"""
import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
EVALUATOR_DIR = BASE_DIR / "apps" / "evaluator"
EVALUATOR_PYTHON = EVALUATOR_DIR / ".venv_ai" / "Scripts" / "python.exe"
BATCH_FACTORY_DIR = BASE_DIR / "apps" / "batch_factory"
BATCH_FACTORY_PYTHON = BATCH_FACTORY_DIR / ".venv_train" / "Scripts" / "python.exe"


def _run(args: list, cwd: Path, step_name: str) -> None:
    result = subprocess.run(
        [str(a) for a in args], cwd=str(cwd),
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        print(f"🚨 {step_name} に失敗しました(exit={result.returncode})。パイプラインを中断します。")
        sys.exit(1)


def run_extraction() -> None:
    """apps/evaluator/scripts/extract_dpo_data.py を実行し、最新のdpo_dataset.jsonlを生成する。"""
    print("🚀 [Step 1/2] DPOデータ抽出を実行します...")
    script = EVALUATOR_DIR / "scripts" / "extract_dpo_data.py"
    _run([EVALUATOR_PYTHON, script], cwd=EVALUATOR_DIR, step_name="DPOデータ抽出")
    print("✅ DPOデータ抽出完了。\n")


def run_training_prepare(run_training: bool) -> None:
    """batch_factory側のDPO学習スクリプトを起動する。

    既定(run_training=False)では --dry-run を付与し、データ受け渡しの検証のみ行う
    (モデルロード/GPU学習は起動しない)。run_training=True の場合のみ実学習を許可する。
    """
    label = "実学習" if run_training else "学習準備(ドライラン)"
    print(f"🚀 [Step 2/2] batch_factory側の{label}を実行します...")
    script = BATCH_FACTORY_DIR / "train_dpo.py"
    args = [BATCH_FACTORY_PYTHON, script]
    if not run_training:
        args.append("--dry-run")
    _run(args, cwd=BATCH_FACTORY_DIR, step_name=label)
    print(f"✅ {label}完了。" + ("" if run_training else " 実学習は起動していません。"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4.12b: DPOパイプライン・オーケストレーター")
    parser.add_argument(
        "--run-training", action="store_true",
        help="安全装置を外し、batch_factory側で実際のGPU学習を開始する(既定は--dry-run)",
    )
    args = parser.parse_args()

    run_extraction()
    run_training_prepare(run_training=args.run_training)

    print("\n🎉 Lv.3 パイプライン(抽出 -> 学習準備)が正常に完走しました。")


if __name__ == "__main__":
    main()

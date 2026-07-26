"""
tools/train_local_model.py
============================
instructions/243(SSoTバックログ「課題P: DPO/SFT完全自動パイプラインの構築」):
tools/extract_training_data.py が data/training/ に生成したインストラクション・
チューニング形式JSONL({"prompt", "response"})を読み込み、ローカルモデルの
SFT/DPO学習を実行する(想定の)パイプラインの骨組み。

【現状】ローカル環境にGPUリソース・学習ライブラリ(Hugging Face `transformers`/`trl`、
または `Unsloth`)が完全に揃っていないため、実際の学習処理(trainer.train() 等)は
_run_training() 内にコメントアウトのプレースホルダーとして残し、実行時は常に
安全なモック処理(数秒待機してから成功ログを出す)にフォールバックする。
学習ライブラリの導入後、_run_training() のコメントを解除して有効化する想定。

使い方:
    uv run python tools/train_local_model.py             # モック実行(既定)
    uv run python tools/train_local_model.py --dry-run    # 同上(明示指定)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRAINING_DATA_DIR = PROJECT_ROOT / "data" / "training"
OUTPUT_MODEL_DIR = PROJECT_ROOT / "models" / "local_finetuned"

MOCK_TRAINING_DURATION_SEC = 2.0


def _load_training_examples() -> list[dict[str, str]]:
    """data/training/ 配下の全JSONLファイルを読み込む。"""
    examples: list[dict[str, str]] = []
    for jsonl_path in sorted(TRAINING_DATA_DIR.glob("*.jsonl")):
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    examples.append(json.loads(line))
    return examples


def _run_training(examples: list[dict[str, str]], adapter_path: Path, dry_run: bool) -> None:
    """SFT/DPO学習処理のプレースホルダー。

    想定ライブラリ: Hugging Face `transformers` / `trl`(SFTTrainer, DPOTrainer)、
    または `Unsloth`。ローカル環境に学習ライブラリ・GPUリソースが揃うまでは
    以下は起動せず、モック処理のみ行う。
    """
    # from trl import SFTConfig, SFTTrainer
    # from unsloth import FastLanguageModel
    #
    # model, tokenizer = FastLanguageModel.from_pretrained(model_name="...")
    # trainer = SFTTrainer(
    #     model=model,
    #     tokenizer=tokenizer,
    #     train_dataset=examples,
    #     args=SFTConfig(output_dir=str(adapter_path)),
    # )
    # trainer.train()
    # trainer.save_model(str(adapter_path))

    if dry_run:
        print("🧪 --dry-run: 実学習はスキップし、モック処理のみ実行します。")
    time.sleep(MOCK_TRAINING_DURATION_SEC)


def main() -> int:
    parser = argparse.ArgumentParser(description="ローカルモデルのSFT/DPO学習パイプライン(骨組み)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="実学習処理を明示的にスキップする(現状、実学習は未接続のため常にモック動作)",
    )
    args = parser.parse_args()

    OUTPUT_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    adapter_path = OUTPUT_MODEL_DIR / "adapter"

    examples = _load_training_examples()
    print(f"📚 学習データを {len(examples)} 件読み込みました({TRAINING_DATA_DIR})")

    print("🧠 学習を開始します...")
    _run_training(examples, adapter_path, dry_run=args.dry_run)
    print(f"✅ 学習が完了しました。モデル/アダプタ出力先: {adapter_path}")

    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())

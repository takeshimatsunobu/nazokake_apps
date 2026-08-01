"""
tools/train_nazo_sft_model.py
================================
「なぞかけSFT」パイプライン専用のエントリーポイント(instructions/279)。

tools/train_unsloth_core.py(なぞかけ学習・Agent学習で共用される学習コアエンジン)へ、
なぞかけSFTドメイン固有の入力データパス・ベースモデル・出力LoRAパスを明示的に渡して
呼び出す。

呼び出し元: (現時点ではオーケストレータ未配線。単独実行専用)
入力データ: tools/extract_dataset.py が出力するSFTデータセット(data/sft_dataset.jsonl、
{"prompt","completion"}のフラット2キー、instructions/278の調査で判明)。

【instructions/275と同様のVRAM排他制御の防弾化】単独実行時(オーケストレータ経由でない
手動実行)でも、推論APIや他パイプラインとのVRAM競合を防ぐため、学習コアエンジンの
呼び出しをVRAMロックで保護する。将来オーケストレータ(tools/mlops_pipeline_nazo.py等)
経由で起動される場合に備え、tools/train_nazo_model.pyと完全に同じ環境変数ガード
(mlops_common.VRAM_LOCK_HELD_BY_PARENT_ENV)を組み込む(親プロセスが既にロックを
保持しているにもかかわらず自身でも取得を試みると、親が子の完了を待ち・子が親の解放を
待つ自己デッドロックに陥るため)。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# `uv run python tools/train_nazo_sft_model.py` のように直接実行すると sys.path[0] は
# tools/ 自身になり、`from tools import train_unsloth_core`(リポジトリ直下のパッケージ
# として参照する絶対import)が ModuleNotFoundError: No module named 'tools' になる。
# tools/train_nazo_model.pyと同じ対処(リポジトリルートを明示的にsys.pathへ追加)。
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tools import mlops_common, train_unsloth_core  # noqa: E402

# なぞかけSFTドメイン固有の定数。
BASE_MODEL = "elyza:8b"
DATASET_PATH = BASE_DIR / "data" / "sft_dataset.jsonl"
OUTPUT_LORA_PATH = BASE_DIR / "models" / "nazo_sft_lora"


def _run_training() -> None:
    train_unsloth_core.run_nazo_sft_training(
        base_model=BASE_MODEL,
        dataset_path=DATASET_PATH,
        output_lora_path=OUTPUT_LORA_PATH,
    )


def main() -> int:
    if os.environ.get(mlops_common.VRAM_LOCK_HELD_BY_PARENT_ENV):
        # オーケストレータ経由: 親が既にロックを保持しているため、自身での取得は
        # スキップする(自己デッドロック回避)。
        _run_training()
        return 0

    lock = mlops_common.acquire_vram_lock_with_backoff()
    try:
        _run_training()
    finally:
        lock.release()
        print("🔓 [VRAM排他制御] VRAMロックを解放しました。")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        # typeshedのsys.stdout/stderrはTextIOとして型付けされreconfigure()を
        # 宣言していないが、実行時は実際にTextIOWrapperであり存在する。
        sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
        sys.stderr.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    sys.exit(main())

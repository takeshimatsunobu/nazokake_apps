"""
tools/train_nazo_model.py
============================
「なぞかけ学習」パイプライン専用のエントリーポイント。

tools/train_unsloth_core.py(なぞかけ学習・Agent学習で共用される学習コアエンジン)へ、
なぞかけドメイン固有の入力データパス・ベースモデル・出力LoRAパスを明示的に渡して
呼び出す(instructions/274: 密結合の解消)。

呼び出し元: tools/mlops_pipeline_nazo.py
入力データ: tools/extract_dataset.py が出力するDPOデータセット(data/dpo_dataset.jsonl)。

【instructions/281: SFT->DPOの学習連鎖】BASE_MODELは生のベースモデル名ではなく、
直前のSFTステップ(tools/train_nazo_sft_model.py)の出力先models/nazo_sft_loraを
指す。DPOはSFTで既に指示追従・基本フォーマットを学習済みのアダプタから選好最適化を
開始することで、なぞかけ生成モデルの学習連鎖(データフライホイールの連続性)を
接合する(instructions/280で判明した、SFT/DPOが互いに無関係な独立学習になっていた
欠落を解消)。

【instructions/275: VRAM排他制御の防弾化】単独実行時(オーケストレータ経由でない
手動実行)でも、推論APIや他パイプラインとのVRAM競合を防ぐため、学習コアエンジンの
呼び出しをVRAMロックで保護する。ただしtools/mlops_pipeline_nazo.py経由で起動された
場合は、親プロセスが既にこのロックを保持済みであるため、自身では再取得しない
(取得を試みると、親が子の完了を待ち・子が親の解放を待つ自己デッドロックに陥る。
詳細はtools/mlops_common.VRAM_LOCK_HELD_BY_PARENT_ENVのdocstring参照)。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# `uv run python tools/train_nazo_model.py` のように直接実行すると sys.path[0] は
# tools/ 自身になり、`from tools import train_unsloth_core`(リポジトリ直下のパッケージ
# として参照する絶対import)が ModuleNotFoundError: No module named 'tools' になる。
# tools/mlops_pipeline_nazo.pyと同じ対処(リポジトリルートを明示的にsys.pathへ追加)。
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tools import mlops_common, train_unsloth_core  # noqa: E402

# なぞかけ学習ドメイン固有の定数。
# 【instructions/281】BASE_MODELは生のベースモデル名("elyza:8b")ではなく、SFTステップ
# (tools/train_nazo_sft_model.py)の出力先(models/nazo_sft_lora)を指す。DPOはこの
# SFT済みアダプタを起点に選好最適化を行う(SFT->DPOの学習連鎖)。
BASE_MODEL = str(BASE_DIR / "models" / "nazo_sft_lora")
DATASET_PATH = BASE_DIR / "data" / "dpo_dataset.jsonl"
OUTPUT_LORA_PATH = BASE_DIR / "models" / "nazo_lora"


def _run_training() -> None:
    # instructions/277: なぞかけ学習データはprompt/chosen/rejected形式(DPO)のため
    # run_dpo_training()を呼ぶ(Agent学習のChatML"messages"形式=SFTとは分岐)。
    train_unsloth_core.run_dpo_training(
        base_model=BASE_MODEL,
        dataset_path=DATASET_PATH,
        output_lora_path=OUTPUT_LORA_PATH,
    )


def main() -> int:
    if os.environ.get(mlops_common.VRAM_LOCK_HELD_BY_PARENT_ENV):
        # tools/mlops_pipeline_nazo.py経由: 親が既にロックを保持しているため、
        # 自身での取得はスキップする(自己デッドロック回避)。
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

"""
tools/train_agent_model.py
=============================
「Agent学習」パイプライン専用のエントリーポイント。

tools/train_unsloth_core.py(なぞかけ学習・Agent学習で共用される学習コアエンジン)へ、
Nazo-Agentドメイン固有の入力データパス・ベースモデル・出力LoRAパスを明示的に渡して
呼び出す(instructions/274: 密結合の解消)。

呼び出し元: tools/mlops_pipeline_agent.py
入力データ: tools/extract_agent_sft.py が出力するChatML形式データセット
(run/dataset/agent_sft.jsonl)。
"""

from __future__ import annotations

import sys
from pathlib import Path

# `uv run python tools/train_agent_model.py` のように直接実行すると sys.path[0] は
# tools/ 自身になり、`from tools import train_unsloth_core`(リポジトリ直下のパッケージ
# として参照する絶対import)が ModuleNotFoundError: No module named 'tools' になる。
# tools/mlops_pipeline_agent.pyと同じ対処(リポジトリルートを明示的にsys.pathへ追加)。
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tools import train_unsloth_core  # noqa: E402

# Agent学習ドメイン固有の定数(tools/mlops_pipeline_agent.pyのBASE_MODEL/AGENT_SFT_PATHと
# 一致させる)。
BASE_MODEL = "qwen2.5-coder:7b"
DATASET_PATH = BASE_DIR / "run" / "dataset" / "agent_sft.jsonl"
OUTPUT_LORA_PATH = BASE_DIR / "models" / "agent_lora"


def main() -> int:
    train_unsloth_core.run_training(
        base_model=BASE_MODEL,
        dataset_path=DATASET_PATH,
        output_lora_path=OUTPUT_LORA_PATH,
    )
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        # typeshedのsys.stdout/stderrはTextIOとして型付けされreconfigure()を
        # 宣言していないが、実行時は実際にTextIOWrapperであり存在する。
        sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
        sys.stderr.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    sys.exit(main())

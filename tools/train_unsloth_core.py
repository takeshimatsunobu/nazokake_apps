"""
tools/train_unsloth_core.py
=============================
Unsloth学習コアエンジン(モック)。

【絶対制約】本モジュールは「なぞかけ学習」および「Agent学習」の両パイプラインで
共用される学習コアエンジンである。個別のドメイン知識や特定のパスをハードコードして
はならない。ベースモデル・入力データセットパス・出力LoRAパスは、必ず呼び出し元
(tools/train_nazo_model.py / tools/train_agent_model.py)が run_training() の引数として
明示的に渡すこと。このモジュール自身はエントリーポイントとしての機能を持たない
(if __name__ == "__main__" ブロックは意図的に置かない)。

【instructions/274: 密結合の解消】旧 tools/train_unsloth.py は、なぞかけ学習・Agent学習の
両パイプラインから引数無し・無区別に同一コマンドで呼び出されており、対象ドメイン
(ベースモデル/データセット/出力先)を区別する仕組みが存在しない密結合状態だった
(instructions/273の調査で発覚)。本ファイルへの改称・関数化と、
tools/train_nazo_model.py・tools/train_agent_model.py という個別エントリーポイントの
新設により、パイプラインごとの関心の分離(SoC)をコードベースで強制する。

以前実装されていた「--ppidを受け取り、デーモンスレッドで数秒おきに親プロセスの死活を
ポーリングし、消失を検知したらos._exit(1)で自爆する」機構(Child Suicide)は、
ポーリング間隔に起因する検知遅延や、ポーリングという仕組み自体の不確実性のため
完全に廃止した(Epic 3)。

プロセスツリーのアトミックな破棄は、呼び出し元(tools/train_nazo_model.py /
tools/train_agent_model.py、さらにその親であるtools/mlops_pipeline_nazo.py /
tools/mlops_pipeline_agent.py)が tools/process_manager.py 経由でOSネイティブな
機構(POSIXのプロセスグループ/Windowsの Job Object)を用いて保証する責務へ
委譲されている。このモジュール自身はもはや自己の生死を監視する必要がなく、
単純なモック処理のみを行う。

今回は実際のUnslothによる学習ではなく、数秒スリープして終了するモック処理。
"""

from __future__ import annotations

import time
from pathlib import Path

MOCK_TRAINING_DURATION_SEC = 5.0


def run_training(*, base_model: str, dataset_path: Path, output_lora_path: Path) -> None:
    """学習処理のコアエンジン(モック)。

    呼び出し元が渡すbase_model/dataset_path/output_lora_pathをそのまま踏襲する
    (このモジュール自身はいずれの値も推測・ハードコードしない)。実装時はここで
    実際のUnsloth学習(FastLanguageModel.from_pretrained -> Trainer.train() ->
    save_pretrained)を行う想定。
    """
    print(
        f"🧠 学習を開始します(モック): base_model={base_model}, "
        f"dataset_path={dataset_path}"
    )
    time.sleep(MOCK_TRAINING_DURATION_SEC)
    print(f"✅ 学習が完了しました(モック): output_lora_path={output_lora_path}")

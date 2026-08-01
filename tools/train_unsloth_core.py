"""
tools/train_unsloth_core.py
=============================
Unsloth学習コアエンジン。

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

【instructions/276: 実学習ロジックの実装】run_training()は、Unslothの4bit量子化
ロード・LoRA(PEFT)・小バッチ+勾配累積・8bit optimizer・短いmax_stepsの組み合わせに
より、限られたVRAM(8GB)でもOOMキラーに落ちないことを優先した設定でSFTTrainerに
よる実学習を行う(apps/batch_factory/train_dpo.py/train_model.pyと同じ、既に実証済みの
Unsloth/TRL呼び出しパターンを踏襲)。

torch/unsloth/datasets/trlはGPU学習専用の重量級依存であり、requirements_orchestrator.txt
(CI/エージェントツール用の軽量な共通環境)には意図的に含めていない。これらを関数内で
遅延importし、該当行にpyright抑制コメントを付与することで、GPU環境の無いマシン
(このモジュールをimportするだけのtools/train_nazo_model.py/train_agent_model.py、
およびCIのPyrightゲート)を壊さない(apps/batch_factory/train_dpo.pyの--dry-run分岐と
同じ設計判断)。

以前実装されていた「--ppidを受け取り、デーモンスレッドで数秒おきに親プロセスの死活を
ポーリングし、消失を検知したらos._exit(1)で自爆する」機構(Child Suicide)は、
ポーリング間隔に起因する検知遅延や、ポーリングという仕組み自体の不確実性のため
完全に廃止した(Epic 3)。

プロセスツリーのアトミックな破棄は、呼び出し元(tools/train_nazo_model.py /
tools/train_agent_model.py、さらにその親であるtools/mlops_pipeline_nazo.py /
tools/mlops_pipeline_agent.py)が tools/process_manager.py 経由でOSネイティブな
機構(POSIXのプロセスグループ/Windowsの Job Object)を用いて保証する責務へ
委譲されている。このモジュール自身はもはや自己の生死を監視する必要がない。
"""

from __future__ import annotations

import gc
from pathlib import Path


def run_training(*, base_model: str, dataset_path: Path, output_lora_path: Path) -> None:
    """学習処理のコアエンジン。

    呼び出し元が渡すbase_model/dataset_path/output_lora_pathをそのまま踏襲する
    (このモジュール自身はいずれの値も推測・ハードコードしない)。

    【VRAM 8GB防弾仕様(instructions/276)】
    - モデルロード: max_seq_length=1024, load_in_4bit=True(VRAM枯渇防止)。
    - PEFT: r=16, target_modules=(7種のattention/MLP射影層), lora_alpha=16。
    - Trainer: per_device_train_batch_size=2, gradient_accumulation_steps=4,
      optim="paged_adamw_8bit", max_steps=60(初期検証用として短めに設定)。
    """
    # unsloth/torch/trl/datasetsはGPU学習専用の重量級依存(requirements_orchestrator.txt
    # には意図的に含めていない)。関数内での遅延importにより、このモジュール自体の
    # importはGPU環境の無いマシンでも安全に行える(実行時に初めて必要になる)。
    import torch  # pyright: ignore[reportMissingImports]
    from unsloth import FastLanguageModel  # pyright: ignore[reportMissingImports]
    from datasets import load_dataset  # pyright: ignore[reportMissingImports]
    from trl import SFTConfig, SFTTrainer  # pyright: ignore[reportMissingImports]

    print(f"🧠 学習を開始します: base_model={base_model}, dataset_path={dataset_path}")

    print(f"[Action] Loading model: {base_model}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base_model,
        max_seq_length=1024,
        dtype=None,
        load_in_4bit=True,
    )

    print("[Action] Configuring LoRA adapters")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=16,
        lora_dropout=0.0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
        use_rslora=False,
    )
    model.print_trainable_parameters()

    print(f"[Action] Loading dataset: {dataset_path}")
    dataset = load_dataset("json", data_files=str(dataset_path), split="train")

    output_lora_path.mkdir(parents=True, exist_ok=True)

    print("[Action] Initializing SFTTrainer")
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=SFTConfig(
            output_dir=str(output_lora_path),
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            optim="paged_adamw_8bit",
            max_steps=60,
            seed=42,
            report_to="none",
        ),
    )

    print("[Action] Training started...")
    try:
        trainer.train()
        print("[Action] Saving LoRA adapter")
        trainer.model.save_pretrained(str(output_lora_path))
        print(f"✅ 学習が完了しました: output_lora_path={output_lora_path}")
    finally:
        # OOM等の例外発生時でも確実にVRAMを解放するフェイルセーフ
        # (apps/batch_factory/train_model.pyと同じ既存パターン)。
        del model
        del tokenizer
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("[Fact] VRAM cleanup complete.")

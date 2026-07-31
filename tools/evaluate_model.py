"""
tools/evaluate_model.py
=========================
学習済みLoRAアダプタのホールドアウト検証(Epic 3 Phase 3)。

将来の拡張を前提とした基礎スケルトン: 最新のLoRAアダプタとテストデータセットを
ロードして推論を実行し、簡易的な正解率を算出する。より厳密なスコアリング
(ルーブリック評価等)は将来の拡張で差し替える想定。
評価結果は run/audit_reports/evaluation_report.json へ記録する。
"""

import gc
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
REPORT_PATH = BASE_DIR / "run" / "audit_reports" / "evaluation_report.json"

ADAPTER_PATH = BASE_DIR / "apps" / "batch_factory" / "models" / "nazokake_elyza_lora"
TEST_DATASET_PATH = BASE_DIR / "apps" / "evaluator" / "data" / "sft_dataset.jsonl"
MAX_SEQ_LENGTH = 1024
HOLDOUT_RATIO = 0.1  # 末尾側N%をホールドアウト検証用に使う(スケルトン方針)


def load_holdout_records(path: Path, holdout_ratio: float = HOLDOUT_RATIO) -> list[dict]:
    """テストデータセットを読み込み、末尾側をホールドアウト分として切り出す。"""
    if not path.exists():
        print(f"[Fatal] Dataset not found at: {path}")
        return []

    records = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not records:
        return []
    holdout_size = max(1, int(len(records) * holdout_ratio))
    return records[-holdout_size:]


def evaluate(adapter_path: Path, test_records: list[dict]) -> dict:
    """LoRAアダプタをロードし、ホールドアウトデータで推論・簡易評価を行う。

    正解率(生成結果に正解のassistant発話が含まれるか)を測る簡易実装。
    """
    import torch
    from unsloth import FastLanguageModel

    model = None
    tokenizer = None
    try:
        print(f"[Action] Loading LoRA adapter: {adapter_path}")
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=str(adapter_path),
            max_seq_length=MAX_SEQ_LENGTH,
            dtype=None,
            load_in_4bit=True,
        )
        FastLanguageModel.for_inference(model)

        correct = 0
        total = len(test_records)
        for record in test_records:
            messages = record.get("messages", [])
            expected = next((m["content"] for m in messages if m.get("role") == "assistant"), "")
            prompt_messages = [m for m in messages if m.get("role") != "assistant"]

            inputs = tokenizer.apply_chat_template(
                prompt_messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
            ).to("cuda")
            with torch.no_grad():
                output_ids = model.generate(inputs, max_new_tokens=256, do_sample=False)
            generated = tokenizer.decode(output_ids[0][inputs.shape[1]:], skip_special_tokens=True)

            if expected.strip() and expected.strip() in generated:
                correct += 1

        accuracy = (correct / total) if total else 0.0
        return {"total_samples": total, "correct": correct, "accuracy": accuracy}
    finally:
        # OOM等の例外発生時でも確実にVRAMを解放するフェイルセーフ。
        if model is not None:
            del model
        if tokenizer is not None:
            del tokenizer
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("[Fact] VRAM cleanup complete.")


def main() -> None:
    test_records = load_holdout_records(TEST_DATASET_PATH)
    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "adapter_path": str(ADAPTER_PATH),
        "test_dataset_path": str(TEST_DATASET_PATH),
    }

    if not ADAPTER_PATH.exists():
        print(f"[Fatal] Adapter not found at: {ADAPTER_PATH}")
        report["status"] = "skipped"
        report["reason"] = "adapter_not_found"
    elif not test_records:
        print(f"[Fatal] No holdout records available from: {TEST_DATASET_PATH}")
        report["status"] = "skipped"
        report["reason"] = "no_test_data"
    else:
        metrics = evaluate(ADAPTER_PATH, test_records)
        report["status"] = "completed"
        report["metrics"] = metrics

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[Fact] Evaluation report saved to: {REPORT_PATH}")


if __name__ == "__main__":
    main()

"""
tools/evaluate_model.py
=========================
なぞかけ生成モデル(ベース+DPO学習済みLoRA)の自動評価ゲート(Epic 3 Phase 3、
実推論への置き換えはinstructions/280)。

ベースモデル(elyza:8b)とDPO学習済みLoRA(models/nazo_lora)をロードし、実データから
サンプルしたお題に対して実際に推論(generate)を行い、生成結果が「とかけて」
「ととく」「その心は」等のなぞかけ基本フォーマットを満たしている割合
(Format Adherence Rate)を測る。既存ベースライン(run/audit_reports/
baseline_metrics_nazo.json)と比較し、退行していなければ合格(Exit 0)、
退行していれば不合格(Exit 1)とする(呼び出し元のtools/mlops_common.run_step()が
非0終了コードを検知し、パイプラインをFail-Fastで停止させる)。

評価結果(生スコアを含む)は run/audit_reports/evaluation_report.json へ、合否に
関わらず必ず記録する(観測性のため)。
"""

import gc
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    # typeshedのsys.stdout/stderrはTextIOとして型付けされreconfigure()を
    # 宣言していないが、実行時は実際にTextIOWrapperであり存在する。
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    sys.stderr.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

BASE_DIR = Path(__file__).resolve().parent.parent
REPORT_PATH = BASE_DIR / "run" / "audit_reports" / "evaluation_report.json"
BASELINE_PATH = BASE_DIR / "run" / "audit_reports" / "baseline_metrics_nazo.json"

BASE_MODEL = "elyza:8b"
ADAPTER_PATH = BASE_DIR / "models" / "nazo_lora"
TEST_DATASET_PATH = BASE_DIR / "data" / "sft_dataset.jsonl"
MAX_SEQ_LENGTH = 1024
SAMPLE_SIZE = 8

# なぞかけの基本フォーマットを構成する必須キーワード。生成結果がこれら全てを
# 含む場合のみ「フォーマット遵守」とみなす(instructions/280)。
FORMAT_KEYWORDS = ("とかけて", "ととく", "その心は")


def load_sample_records(path: Path, sample_size: int = SAMPLE_SIZE) -> list[dict]:
    """テストデータセットの先頭からsample_size件を決定論的にサンプルする。

    ランダムサンプリングにしないのは、ベースラインとの比較が意味を持つよう、
    実行のたびに同じお題集合で評価する必要があるため(tools/extract_dataset.pyの
    seed=固定の学習と同じ再現性の思想)。
    """
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

    return records[:sample_size]


def _is_format_adherent(generated_text: str) -> bool:
    """生成テキストがなぞかけの基本フォーマット(3キーワード全て)を満たすか判定する。"""
    return all(keyword in generated_text for keyword in FORMAT_KEYWORDS)


def evaluate(base_model: str, adapter_path: Path, test_records: list[dict]) -> dict:
    """ベースモデル+DPO学習済みLoRAで実推論を行い、Format Adherence Rateを測る。

    tools/extract_dataset.pyが出力する"prompt"はodai(お題)そのままの生文字列
    (指示テンプレートで包んでいない)であるため、学習時と同じ分布に合わせ、
    評価時もodaiをそのままモデルへ入力する。
    """
    import torch  # pyright: ignore[reportMissingImports]
    from unsloth import FastLanguageModel  # pyright: ignore[reportMissingImports]

    model = None
    tokenizer = None
    try:
        print(f"[Action] Loading base model: {base_model}")
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=base_model,
            max_seq_length=MAX_SEQ_LENGTH,
            dtype=None,
            load_in_4bit=True,
        )
        print(f"[Action] Loading DPO-trained LoRA adapter: {adapter_path}")
        model.load_adapter(str(adapter_path))
        FastLanguageModel.for_inference(model)

        adherent = 0
        total = len(test_records)
        for record in test_records:
            odai = record.get("prompt", "")
            inputs = tokenizer(odai, return_tensors="pt").to("cuda")
            with torch.no_grad():
                output_ids = model.generate(**inputs, max_new_tokens=256, do_sample=False)
            generated = tokenizer.decode(
                output_ids[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
            )
            if _is_format_adherent(generated):
                adherent += 1

        format_adherence_rate = (adherent / total) if total else 0.0
        return {
            "total_samples": total,
            "format_adherent_count": adherent,
            "format_adherence_rate": format_adherence_rate,
        }
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


def _load_baseline() -> dict | None:
    if not BASELINE_PATH.exists():
        return None
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _save_baseline(metrics: dict) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def evaluate_quality_gate(report: dict) -> bool:
    """定量評価ゲート: Format Adherence Rateが既存ベースラインを下回っていないかを判定する。

    report["status"]が"completed"でない場合(アダプタ未検出/テストデータ無し等)は、
    スコアそのものを計測できていないため、非退行を確認できず安全側に倒して不合格とする。
    """
    if report.get("status") != "completed":
        print(
            f"🚨 [ゲート判定] 評価が完了しませんでした(status={report.get('status')}, "
            f"reason={report.get('reason')})。非退行を確認できないため、"
            "安全側に倒して不合格とします。"
        )
        return False

    rate = report.get("metrics", {}).get("format_adherence_rate")
    baseline = _load_baseline()
    baseline_rate = baseline.get("format_adherence_rate") if baseline else None

    print(f"📊 Format Adherence Rate: {rate} (ベースライン: {baseline_rate})")

    if baseline_rate is None:
        print("ℹ️  ベースラインが存在しないため、退行判定はスキップします。")
    else:
        delta = rate - baseline_rate
        print(f"📊 Format Adherence Rate Delta: {delta}")
        if delta < 0:
            print("🚨 [ゲート判定] Format Adherence Rateが現行ベースラインを下回りました。")
            return False

    _save_baseline({"format_adherence_rate": rate})
    return True


def main() -> int:
    test_records = load_sample_records(TEST_DATASET_PATH)
    report: dict[str, Any] = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "base_model": BASE_MODEL,
        "adapter_path": str(ADAPTER_PATH),
        "test_dataset_path": str(TEST_DATASET_PATH),
    }

    if not ADAPTER_PATH.exists():
        print(f"[Fatal] Adapter not found at: {ADAPTER_PATH}")
        report["status"] = "skipped"
        report["reason"] = "adapter_not_found"
    elif not test_records:
        print(f"[Fatal] No test records available from: {TEST_DATASET_PATH}")
        report["status"] = "skipped"
        report["reason"] = "no_test_data"
    else:
        metrics = evaluate(BASE_MODEL, ADAPTER_PATH, test_records)
        report["status"] = "completed"
        report["metrics"] = metrics

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[Fact] Evaluation report saved to: {REPORT_PATH}")

    if evaluate_quality_gate(report):
        print("✅ [ゲート判定] 退行なし。合格。")
        return 0
    print("🛑 [ゲート判定] 不合格。")
    return 1


if __name__ == "__main__":
    sys.exit(main())

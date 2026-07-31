"""
tools/extract_agent_sft.py
============================
Nazo-Agent(Claude)の推論軌跡(エラーログ+ASTマップ -> 修正指令)を、ローカルLLM
ファインチューニング用のChatML形式JSONLとして抽出・蓄積する(Epic 1拡張)。

入力: run/audit_reports/error_log.txt, run/audit_reports/static_context.md
出力(記録元): run/audit_reports/triage_result.json
保存先: run/dataset/agent_sft.jsonl (1レコード1行、追記)
"""

import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
AUDIT_DIR = BASE_DIR / "run" / "audit_reports"
DATASET_DIR = BASE_DIR / "run" / "dataset"

ERROR_LOG_PATH = AUDIT_DIR / "error_log.txt"
STATIC_CONTEXT_PATH = AUDIT_DIR / "static_context.md"
TRIAGE_RESULT_PATH = AUDIT_DIR / "triage_result.json"
OUTPUT_PATH = DATASET_DIR / "agent_sft.jsonl"

SYSTEM_PROMPT = (
    "あなたはNazo-Agentの自律推論エンジンです。"
    "エラーログとASTマップから、修正対象と内容を決定してください。"
)


def build_chatml_record() -> dict | None:
    """3つの入出力ファイルが揃っている場合のみ、ChatML形式の1レコードを組み立てて返す。"""
    if not (ERROR_LOG_PATH.exists() and STATIC_CONTEXT_PATH.exists() and TRIAGE_RESULT_PATH.exists()):
        print("⚠️ 入出力ファイルが揃っていないため、抽出をスキップしました。")
        return None

    error_log = ERROR_LOG_PATH.read_text(encoding="utf-8")
    static_context = STATIC_CONTEXT_PATH.read_text(encoding="utf-8")
    triage_result = TRIAGE_RESULT_PATH.read_text(encoding="utf-8")

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"【エラーログ】\n{error_log}\n\n【AST要約マップ】\n{static_context}",
            },
            {"role": "assistant", "content": triage_result},
        ]
    }


def append_record(record: dict) -> None:
    """レコードを1行のJSON文字列として agent_sft.jsonl へ追記する。"""
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    record = build_chatml_record()
    if record is None:
        sys.exit(1)

    append_record(record)
    print(f"✅ 推論軌跡を抽出し、{OUTPUT_PATH} へ追記しました。")


if __name__ == "__main__":
    main()

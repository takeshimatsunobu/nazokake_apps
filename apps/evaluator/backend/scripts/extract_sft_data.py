"""SFT（教師あり微調整）用 特級データ抽出スクリプト（MLOps 基盤 V6 隠しステータス統合版）。

1. is_golden_data == True または is_approved == True (手動承認済み) -> スコア4.0以上
2. status == 2 (Web版) または status == "all_completed" (工場版) -> スコア4.1以上（自動昇格）
"""

import argparse
import json
import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import firebase_admin
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: S110 (reconfigure非対応環境向けの意図的なフォールバック)
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "data", "sft_dataset.jsonl")

THRESHOLD_MANUAL = 4.0
THRESHOLD_AUTO = 4.1


def init_db():
    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})
    return firestore.client()


def compose_text(odai: str, result: dict) -> str:
    toku = (result or {}).get("toku", "")
    kokoro = (result or {}).get("kokoro", "")
    return f"「{odai}」とかけて、「{toku}」と解く。\nその心は、{kokoro}"


def to_score(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main(dry_run: bool = False, out_path: str = OUTPUT_PATH):
    db = init_db()
    print(
        f"🔍 Firestore からSFT用データの全量走査を開始（自動昇格閾値: {THRESHOLD_AUTO} 以上）..."
    )

    system_prompt = "あなたはユーモアのセンスに優れた、なぞかけAIです。"
    try:
        cfg = db.collection("system_configs").document("ai_settings").get()
        if cfg.exists:
            system_prompt = (cfg.to_dict() or {}).get(
                "system_prompt", system_prompt
            ) or system_prompt
    except Exception as e:
        print(f"⚠️ ai_settings 取得失敗: {e}")

    sft_samples = []
    seen_doc_ids = set()

    # 1. 手動承認済み
    query_golden = (
        db.collection("nazokake_items")
        .where(filter=FieldFilter("is_golden_data", "==", True))
        .stream()
    )
    query_approved = (
        db.collection("nazokake_items")
        .where(filter=FieldFilter("is_approved", "==", True))
        .stream()
    )

    # 2. 評価完了済み全量（Web版: status == 2）
    print("⏳ 「status=2 (Webアプリ版)」をスキャン中...")
    query_evaluated_int = (
        db.collection("nazokake_items")
        .where(filter=FieldFilter("status", "==", 2))
        .stream()
    )

    # 3. 評価完了済み全量（バッチ工場版: status == "all_completed"）
    print("⏳ 「status='all_completed' (バッチ工場版)」をスキャン中...")
    query_evaluated_str = (
        db.collection("nazokake_items")
        .where(filter=FieldFilter("status", "==", "all_completed"))
        .stream()
    )

    for stream in [
        query_golden,
        query_approved,
        query_evaluated_int,
        query_evaluated_str,
    ]:
        for doc in stream:
            if doc.id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc.id)

            item = doc.to_dict() or {}
            # 🛡️ 防弾: 旧キー名(A_TITLE)への安全なフォールバック
            odai_raw = item.get("odai") or item.get("A_TITLE") or ""
            odai = str(odai_raw).strip()
            if not odai:
                continue

            is_manual_approved = item.get("is_golden_data", False) or item.get(
                "is_approved", False
            )
            texts_to_extract = []

            # 🛡️ 防弾V6: 全モデル（gemini, elyza, llmjp）のスコアを動的スキャン
            for key, value in item.items():
                if key.startswith("s_total"):
                    score = to_score(value)
                    if score is not None:
                        if (is_manual_approved and score >= THRESHOLD_MANUAL) or (
                            not is_manual_approved and score >= THRESHOLD_AUTO
                        ):
                            suffix = key.replace("s_total", "")
                            result_key = f"result{suffix}"
                            text_key = f"nazokake_text{suffix}"

                            text = (item.get(text_key) or "").strip()
                            if not text and item.get(result_key):
                                text = compose_text(odai, item.get(result_key))
                            if text and text not in texts_to_extract:
                                texts_to_extract.append(text)

            for text in texts_to_extract:
                sft_samples.append(
                    {
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": f"お題「{odai}」でなぞかけを作成してください。",
                            },
                            {"role": "assistant", "content": text},
                        ]
                    }
                )

    print(f"📊 クオリティゲートを突破した模範解答総数: {len(sft_samples)} 件")

    if dry_run:
        print("🧪 [DRY-RUN] 完了。")
        return

    if not sft_samples:
        print(
            "⚠️ 抽出条件を満たすデータが0件のため、ファイルの書き出しをスキップします。"
        )
        return

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for sample in sft_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(
        f"✅ SFT用・データセット（V6: 隠しステータス統合版）の錬成が完了しました → {out_path}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", default=OUTPUT_PATH)
    args = parser.parse_args()
    main(dry_run=args.dry_run, out_path=args.out)

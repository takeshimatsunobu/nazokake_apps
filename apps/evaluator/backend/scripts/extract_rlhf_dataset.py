"""RLHF/DPO 学習データ抽出スクリプト（MLOps 基盤 V2）。

telemetry_logs の「差分抽出（Incremental Fetch）」と nazokake_items の
「バルクフェッチ（get_all）」を実装し、10,000人規模のアクセスによる
FirestoreのRead課金爆発とN+1問題を物理的に防いだ完全防弾版。

出力 (data/rlhf_dataset.jsonl, 1行1サンプル):
  { "odai", "model", "model_key", "text", "score", "score_type", "human_comment",
    "user_slug", "doc_id", "system_prompt", "dpo_pair_id", "is_golden_data", "data_source" }
"""

import json
import os
import sys
from datetime import datetime

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import firebase_admin
from firebase_admin import firestore

from nazokake_core.training_filter import is_valid_for_training

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: S110 (reconfigure非対応環境向けの意図的なフォールバック)
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "data", "rlhf_dataset.jsonl")
STATE_PATH = os.path.join(PROJECT_ROOT, "data", "extract_state.json")

EVAL_PREFIX = "gen_eval:"

MODEL_IDS = {
    "gemini": "gemini-3.5-flash",
    "elyza": os.environ.get("LLMJP_MODEL", "elyza:8b"),
    "llmjp": os.environ.get("LLMJP_MODEL", "elyza:8b"),
    "swallow": os.environ.get("LLMJP_MODEL", "swallow:13b"),
}

MODEL_FIELDS = {
    "gemini": ("result_gemini", "nazokake_text", "result"),
    "elyza": ("result_llmjp", "nazokake_text_llmjp", None),
    "llmjp": ("result_llmjp", "nazokake_text_llmjp", None),
    "swallow": ("result_llmjp", "nazokake_text_llmjp", None),
}


def init_db():
    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})
    return firestore.client()


def compose_text(odai: str, result: dict) -> str:
    toku = (result or {}).get("toku", "")
    kokoro = (result or {}).get("kokoro", "")
    return f"「{odai}」とかけて、「{toku}」と解く。\nその心は、{kokoro}"


def resolve_text(item: dict, model_key: str) -> str:
    result_field, text_field, alt_result_field = MODEL_FIELDS.get(
        model_key, (None, None, None)
    )
    if not result_field:
        return ""
    text = (item.get(text_field) or "").strip() if text_field else ""
    if text:
        return text
    result = (
        item.get(result_field)
        or (item.get(alt_result_field) if alt_result_field else None)
        or {}
    )
    if result.get("toku") or result.get("kokoro"):
        return compose_text(item.get("odai", ""), result)
    return ""


def to_score(duration):
    try:
        f = float(duration)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


def ts_key(ts):
    return ts if ts is not None else 0


def main(
    dry_run: bool = False,
    limit: int = None,
    out_path: str = OUTPUT_PATH,
    full_scan: bool = False,
):
    db = init_db()

    system_prompt = ""
    try:
        cfg = db.collection("system_configs").document("ai_settings").get()
        if cfg.exists:
            system_prompt = (cfg.to_dict() or {}).get("system_prompt", "") or ""
    except Exception as e:
        print(f"⚠️ ai_settings 取得失敗: {e}")

    # 過去の抽出状態（タイムスタンプ）のロード
    last_ts = None
    if not full_scan and os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
                if state.get("last_telemetry_ts"):
                    last_ts = datetime.fromisoformat(state["last_telemetry_ts"])
        except Exception as e:
            print(f"⚠️ 状態ファイル読み込み失敗: {e}")

    # 既存データをローカルDBとしてメモリに展開（重複排除・Upsert用）
    final_records = {}
    if not full_scan and os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    final_records[(rec["doc_id"], rec["model_key"])] = rec
            print(
                f"📥 既存データ {len(final_records)} 件をロードしました（差分更新を行います）。"
            )
        except Exception as e:
            print(f"⚠️ 既存jsonl読み込み失敗: {e}")

    # Phase 1: テレメトリの差分抽出（不等号は1種類のみのFirestore制約を順守）
    eval_logs = []
    max_ts = last_ts
    query = db.collection("telemetry_logs")

    if last_ts:
        print(f"🔍 [Phase 1] 差分抽出: {last_ts} 以降のログを取得します...")
        query = query.where("timestamp", ">", last_ts).order_by("timestamp")
    else:
        print("🔍 [Phase 1] フルスキャン: 全てのログを取得します...")

    for doc in query.stream():
        d = doc.to_dict() or {}
        ts = d.get("timestamp")

        # 最大タイムスタンプの更新
        if ts and (max_ts is None or ts > max_ts):
            max_ts = ts

        if d.get("invalidated"):
            continue

        # Python側でイベント名の前方一致をフィルタリング
        event = d.get("event_name", "") or ""
        if not event.startswith(EVAL_PREFIX):
            continue

        model_key = event[len(EVAL_PREFIX) :].strip().lower()
        doc_id = d.get("tab_name")
        score = to_score(d.get("duration"))
        if not doc_id or score is None or score <= 0:
            continue

        eval_logs.append(
            {
                "model_key": model_key,
                "doc_id": doc_id,
                "score": score,
                "comment": (d.get("comment") or "").strip() or None,
                "user_slug": d.get("user_slug", ""),
                "ts": ts,
            }
        )

    print(f"📊 新規取得された評価イベント: {len(eval_logs)} 件")

    latest = {}
    for e in eval_logs:
        k = (e["user_slug"], e["doc_id"], e["model_key"])
        if k not in latest or ts_key(e["ts"]) > ts_key(latest[k]["ts"]):
            latest[k] = e
    deduped = list(latest.values())

    # --- 究極のN+1解消：バルクフェッチ (db.get_all) ---
    item_cache = {}
    missing_doc_ids = list(set(e["doc_id"] for e in deduped))
    if missing_doc_ids:
        print(
            f"📦 nazokake_items をバルクフェッチします ({len(missing_doc_ids)} 件)..."
        )
        # Firestoreの制限を考慮し、100件ずつチャンク処理
        for i in range(0, len(missing_doc_ids), 100):
            chunk = missing_doc_ids[i : i + 100]
            refs = [db.collection("nazokake_items").document(did) for did in chunk]
            try:
                docs = db.get_all(refs)
                for doc in docs:
                    item_cache[doc.id] = doc.to_dict() if doc.exists else None
            except Exception as e:
                print(f"⚠️ バルクフェッチ中にエラー: {e}")

    skipped_no_item = skipped_no_text = 0

    for e in deduped:
        item = item_cache.get(e["doc_id"])
        if not item:
            skipped_no_item += 1
            continue
        text = resolve_text(item, e["model_key"])
        if not text:
            skipped_no_text += 1
            continue

        # Upsert: 既存レコードを上書き（または新規追加）
        final_records[(e["doc_id"], e["model_key"])] = {
            "odai": item.get("odai", ""),
            "model": MODEL_IDS.get(e["model_key"], e["model_key"]),
            "model_key": e["model_key"],
            "text": text,
            "score": e["score"],
            "score_type": "human_eval",
            "human_comment": e["comment"],
            "user_slug": e["user_slug"],
            "doc_id": e["doc_id"],
            "system_prompt": system_prompt,
            "dpo_pair_id": item.get("dpo_pair_id", ""),
            "is_golden_data": bool(item.get("is_golden_data", False)),
            "data_source": "telemetry",
        }

    # Phase 2: Golden Data および バッチ工場生成データの直接スキャン
    print("🔍 [Phase 2] Golden Data および バッチ工場データの直接スキャンを実行中...")
    direct_count = 0
    try:
        docs_golden = (
            db.collection("nazokake_items").where("is_golden_data", "==", True).stream()
        )
        # 【修正】batch/main.py・batch/run_matrix.py はGemini生成物を"batch_factory_gemini"、
        # ELYZA(Ollama)生成物を"batch_factory_local"としてsourceに書き分ける
        # (dpo_pair_idで同じペアに紐付けつつ、別ドキュメントとして保存する設計)。
        # 以前はここが"batch_factory_gemini"のみを対象にしており、"batch_factory_local"
        # (ELYZA側)のドキュメントが一切フェッチされていなかった。DPOペア抽出は同一
        # dpo_pair_id配下に2件(chosen/rejected)揃って初めて成立する(build_pairs()参照)ため、
        # 相方が常に欠落し、batch_factory由来のDPOペアが実質1件も生成されない状態だった。
        docs_batch = (
            db.collection("nazokake_items")
            .where("source", "in", ["batch_factory_gemini", "batch_factory_local"])
            .stream()
        )

        for docs in [docs_golden, docs_batch]:
            for doc in docs:
                doc_id = doc.id
                item = doc.to_dict() or {}

                # 【毒入れ防止】nazokake_itemsには本フィールドが存在しないため、
                # is_valid_for_training()は常にTrueへフォールバックし実質no-op
                # (旧データは引き続き全件対象のまま)。nazokake_results側の
                # 明示的なFalse除外のためにここでも一貫して適用しておく。
                if not is_valid_for_training(item):
                    continue

                dpo_pair_id = item.get("dpo_pair_id", "")
                is_golden_data = bool(item.get("is_golden_data", False))

                if item.get("source") in ("batch_factory_gemini", "batch_factory_local"):
                    model_id = item.get("model_id", "unknown").lower()
                    model_key = (
                        "elyza"
                        if "elyza" in model_id
                        else (
                            "swallow"
                            if "swallow" in model_id
                            else ("gemini" if "gemini" in model_id else "unknown")
                        )
                    )

                    text = item.get("nazokake_text", "").strip()
                    if not text and item.get("result"):
                        text = compose_text(item.get("odai", ""), item.get("result"))

                    if text:
                        key = (doc_id, model_key)
                        final_records[key] = {
                            "odai": item.get("odai", ""),
                            "model": item.get("model_id", "unknown"),
                            "model_key": model_key,
                            "text": text,
                            "score": item.get("s_total", 0.0),
                            "score_type": "ai_eval",
                            "human_comment": None,
                            "user_slug": "batch_factory",
                            "doc_id": doc_id,
                            "system_prompt": system_prompt,
                            "dpo_pair_id": dpo_pair_id,
                            "is_golden_data": is_golden_data,
                            "data_source": "batch_direct",
                        }
                        direct_count += 1
                else:
                    for mk in ["gemini", "elyza"]:
                        text = resolve_text(item, mk)
                        if text:
                            key = (doc_id, mk)
                            score_field = (
                                "s_total" if mk == "gemini" else "s_total_llmjp"
                            )
                            final_records[key] = {
                                "odai": item.get("odai", ""),
                                "model": MODEL_IDS.get(mk, mk),
                                "model_key": mk,
                                "text": text,
                                "score": item.get(score_field, 0.0),
                                "score_type": "ai_eval",
                                "human_comment": None,
                                "user_slug": "evaluator_direct",
                                "doc_id": doc_id,
                                "system_prompt": system_prompt,
                                "dpo_pair_id": dpo_pair_id,
                                "is_golden_data": is_golden_data,
                                "data_source": "golden_direct",
                            }
                            direct_count += 1

        # 【Phase4追加】apps/persona_router が書き込む nazokake_results コレクションの
        # 直接スキャン。従来このコレクションはどの抽出スクリプトからも参照されておらず、
        # is_valid_for_training=false(荒らし入力を「エンタメ化」した非学習対象生成物)が
        # 立っていても、それを見る下流処理が存在しなかった。ここで初めて接続する。
        # スコア(s_total)は生成時点では未採点で、scripts/evaluate_persona_results.py
        # による事後評価バッチが書き戻すまで存在しないため、未評価分は自然にスキップされる
        # (次回の差分実行時に評価が済んでいれば拾われる)。
        persona_results_count = 0
        docs_persona_results = db.collection("nazokake_results").stream()
        for doc in docs_persona_results:
            doc_id = doc.id
            item = doc.to_dict() or {}

            if not is_valid_for_training(item):
                continue

            text = (item.get("nazokake_text") or "").strip()
            score = to_score(item.get("s_total"))
            if not text or score is None:
                continue

            model_id = (item.get("generator_model_id") or "gemini").lower()
            model_key = "gemini" if "gemini" in model_id else model_id

            final_records[(doc_id, model_key)] = {
                "odai": item.get("odai", ""),
                "model": item.get("generator_model_id", "unknown"),
                "model_key": model_key,
                "text": text,
                "score": score,
                "score_type": "ai_eval",
                "human_comment": None,
                "user_slug": "persona_router",
                "doc_id": doc_id,
                "system_prompt": system_prompt,
                # persona_router側にdpo_pair_idの概念は無い(1お題=1回生成、対になる
                # rejected応答が存在しない)ため空文字とする。DPO用の選好ペアは
                # 代わりにPhase3の添削(corrections)データ(元AI応答=rejected /
                # 添削後=chosen)から別途構成する設計とする。
                "dpo_pair_id": "",
                "is_golden_data": False,
                "data_source": "persona_router",
            }
            persona_results_count += 1
        print(f"📥 nazokake_results からの直接スキャン: {persona_results_count} 件")
    except Exception as e:
        print(
            f"⚠️ 直接スキャン中にエラー発生（インデックスが必要な場合があります）: {e}"
        )

    print(f"📥 直接スキャンによる更新/追加レコード: {direct_count} 件")

    records = list(final_records.values())

    if limit is not None:
        records = records[:limit]

    by_model = {}
    for r in records:
        by_model[r["model"]] = by_model.get(r["model"], 0) + 1
    if by_model:
        print(
            "   モデル別内訳: "
            + ", ".join(f"{k}={v}" for k, v in sorted(by_model.items()))
        )

    if dry_run:
        print(f"🧪 [DRY-RUN] ファイルは書き込みません（対象 {len(records)} 件）。")
        return

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 状態ファイル（タイムスタンプ）の保存
    if max_ts and hasattr(max_ts, "isoformat"):
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"last_telemetry_ts": max_ts.isoformat()}, f)

    print(f"✅ {len(records)} 件を書き出しました → {out_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="telemetry_logs × nazokake_items を結合し RLHF/DPO 用 JSONL を抽出する"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ファイルに書かず件数と先頭サンプルだけ表示",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="出力件数の上限（テスト用）"
    )
    parser.add_argument(
        "--out", default=OUTPUT_PATH, help=f"出力パス（既定: {OUTPUT_PATH}）"
    )
    parser.add_argument(
        "--full", action="store_true", help="差分抽出を無視し、全データを再スキャンする"
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run, limit=args.limit, out_path=args.out, full_scan=args.full)

"""SFT（教師あり微調整）用 特級データ抽出スクリプト（MLOps 基盤 V6 隠しステータス統合版）。

1. is_golden_data == True または is_approved == True (手動承認済み) -> スコア4.0以上
2. status == 2 (Web版) または status == "all_completed" (工場版) -> スコア4.1以上（自動昇格）

【persona_feature_plan_v3.md Phase8 §5.1/§5.2】出力形式を「完成文(語り手ペルソナの
文体込みで組み立てたcompose_text()の1本の文字列)」から、構造化された
odai → toku + kokoro へ変更する。理由はtools/extract_training_data.pyの同種の
変更と同じで、完成文には語り手ペルソナの文体が焼き込まれてしまい、この構造
(第1層)学習データにペルソナごとの文体が混入することを防ぐため。あわせて
§5.1の共通エンベロープをサンプルごとに適用する。
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

from nazokake_core.dataset_envelope import build_envelope
from nazokake_core.narrator_personas import get_persona
from nazokake_core.training_filter import is_valid_for_training

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


class _OwnerUidCache:
    """narrator_persona_id -> owner_uid をFirestoreへ都度問い合わせず使い回すための
    軽量キャッシュ(persona_idの種類は実運用でも高々数十件規模のため)。"""

    def __init__(self, db):
        self._db = db
        self._cache: dict[str, str | None] = {}

    def get(self, persona_id: str | None) -> str | None:
        if not persona_id:
            return None
        if persona_id not in self._cache:
            doc = get_persona(self._db, persona_id)
            self._cache[persona_id] = (doc or {}).get("owner_uid")
        return self._cache[persona_id]


def to_score(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _created_at_iso(value) -> str:
    """Firestoreのcreated_atは、書き込み経路によってISO8601文字列の場合と
    google.cloud.firestore_v1._helpers.DatetimeWithNanoseconds(datetime.datetimeの
    サブクラス、json.dumps非対応)の場合の両方があるため、ここで文字列へ正規化する。
    実機データで後者が実在することが判明した(json.dumps時のTypeErrorで発覚)。
    """
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _make_envelope(*, doc_id, source_collection, odai, toku, kokoro, item, system_prompt, owner_uid_cache):
    """§5.1のエンベロープでラップした、messages形式(chat-SFT用)のサンプルを1件作る。

    payload自体は「odai/toku/kokoro」ではなく既存の出力契約(messages配列)を
    維持しつつ、assistantのcontentを完成文(語り手ペルソナの文体込み)ではなく
    toku/kokoroのみの構造化JSON文字列に変更する(§5.2)。
    """
    narrator_persona_id = item.get("narrator_persona_id") or "No_Data"
    narrator_persona_version_id = item.get("narrator_persona_version_id") or "No_Data"
    assistant_content = json.dumps({"toku": toku, "kokoro": kokoro}, ensure_ascii=False)
    return build_envelope(
        dataset_layer="structure",
        source_collection=source_collection,
        source_doc_id=doc_id,
        narrator_persona_id=narrator_persona_id,
        narrator_persona_version_id=narrator_persona_version_id,
        data_origin=item.get("data_origin") or "no_data",
        owner_uid=owner_uid_cache.get(narrator_persona_id),
        created_at=_created_at_iso(item.get("created_at")),
        payload={
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"お題「{odai}」でなぞかけを作成してください。",
                },
                {"role": "assistant", "content": assistant_content},
            ]
        },
    )


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

    owner_uid_cache = _OwnerUidCache(db)
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
            # 🛡️ 毒入れ防止(Phase4): nazokake_itemsには本フィールドが存在しない
            # ため実質no-op(旧データは引き続き全件対象)。
            if not is_valid_for_training(item):
                continue
            # 🛡️ 防弾: 旧キー名(A_TITLE)への安全なフォールバック
            odai_raw = item.get("odai") or item.get("A_TITLE") or ""
            odai = str(odai_raw).strip()
            if not odai:
                continue

            is_manual_approved = item.get("is_golden_data", False) or item.get(
                "is_approved", False
            )
            pairs_to_extract = []

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

                            # §5.2: toku/kokoroへ分解できない行(result{suffix}が
                            # 無く、完成文(nazokake_text{suffix})しか無い旧世代
                            # データ)は、完成文からの逆算パースが文体混入防止と
                            # いう目的に反するため、意図的にスキップする。
                            result_dict = item.get(result_key) or {}
                            toku = str(result_dict.get("toku") or "").strip()
                            kokoro = str(result_dict.get("kokoro") or "").strip()
                            if toku and kokoro and (toku, kokoro) not in pairs_to_extract:
                                pairs_to_extract.append((toku, kokoro))

            for toku, kokoro in pairs_to_extract:
                sft_samples.append(
                    _make_envelope(
                        doc_id=doc.id,
                        source_collection="nazokake_items",
                        odai=odai,
                        toku=toku,
                        kokoro=kokoro,
                        item=item,
                        system_prompt=system_prompt,
                        owner_uid_cache=owner_uid_cache,
                    )
                )

    # 【Phase4追加】apps/persona_main_function が書き込む nazokake_results コレクションも
    # SFT抽出の対象に含める。is_golden_data/is_approved/statusの概念がこのコレクションには
    # 存在しないため、自動昇格パス(THRESHOLD_AUTO以上)相当の単一ゲートのみを適用する。
    # 未評価(s_totalが無い)ドキュメントはscripts/evaluate_persona_results.pyによる
    # 事後評価バッチが走るまで自然にスキップされる。
    print("⏳ 「nazokake_results (persona_main_function版)」をスキャン中...")
    persona_sft_count = 0
    for doc in db.collection("nazokake_results").stream():
        item = doc.to_dict() or {}
        if not is_valid_for_training(item):
            continue

        odai = str(item.get("odai") or "").strip()
        toku = str(item.get("toku") or "").strip()
        kokoro = str(item.get("kokoro") or "").strip()
        score = to_score(item.get("s_total"))
        if not odai or not toku or not kokoro or score is None or score < THRESHOLD_AUTO:
            continue

        # nazokake_resultsにはnarrator_persona_id専用フィールドが無く、
        # persona_idそのものを論理参照として使う設計(Phase5の既存方針、
        # apps/persona_main_function/api/routers/generate.pyのコメント参照)。
        item_for_envelope = dict(item)
        item_for_envelope["narrator_persona_id"] = item.get("persona_id")
        sft_samples.append(
            _make_envelope(
                doc_id=doc.id,
                source_collection="nazokake_results",
                odai=odai,
                toku=toku,
                kokoro=kokoro,
                item=item_for_envelope,
                system_prompt=system_prompt,
                owner_uid_cache=owner_uid_cache,
            )
        )
        persona_sft_count += 1
    print(f"📥 nazokake_results からの追加サンプル: {persona_sft_count} 件")

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

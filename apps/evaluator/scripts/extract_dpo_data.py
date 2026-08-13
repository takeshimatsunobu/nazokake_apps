"""
extract_dpo_data.py
====================
DPO(Direct Preference Optimization)用データセット抽出スクリプト。

Phase 4.11 で全面改修:
- 旧 status==2 / user_evaluations(現行の書き込み経路では一切使われていない廃止済み
  フィールド)を破棄し、実際に運用されている gemini_status / elyza_status による
  管理者キュレーションに追従する。
- Phase 4 で蓄積される user_feedbacks コレクションを統合する。
    Tier A: 同一 doc_id 内での Gemini/ELYZA 直接比較(pair_type="same_prompt")を優先。
    Tier B: スコアバケットによる横断比較(pair_type="cross_prompt")で補完。
  管理者キュレーション側も同じ Tier A/B 構造で抽出する(1ドキュメントが両モデルの
  出力を持つ場合は同一プロンプト比較、片側のみキュレーション済みならバケット比較)。
- 出力は従来通り data/dpo_dataset.jsonl。各行に "source"(admin/user) と
  "pair_type"(same_prompt/cross_prompt) のメタデータを付与する。

【persona_feature_plan_v3.md Phase8 §5.3】user_feedbacks由来(source=="user")の
ペアに以下2点を追加する(管理者キュレーション(source=="admin")は人間の審査
ゲートを既に通過しているため対象外、計画書の表の通り):
  1. 自己評価の除外: なぞかけを生んだ語り手ペルソナの所有者(narrator_personas.
     owner_uid)が、自分自身の作品を評価したuser_feedbacksは学習ペアの根拠と
     して使わない(自己強化バイアス防止)。
  2. 寄与上限: 単一owner_uid・単一narrator_persona_version_idのいずれかが
     user由来ペア全体の5%を超えて寄与しないようサンプリングする(一部の
     ユーザー/ペルソナが優先選好データを支配することを防ぐ)。

このスクリプトは apps/evaluator/.venv_ai という専用の最小限AI実行環境の
サブプロセスとして起動される(tools/run_dpo_pipeline.py参照)ため、
nazokake_coreパッケージがインストールされている保証が無い。このため
narrator_personasの読み取りはnazokake_core.narrator_personasをimportせず、
既存の設計方針(_fetch_nazokake_items_by_ids等)に倣い素のFirestore
クライアントで直接行う。
"""
import json
import math
import random
from collections import defaultdict
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

GOOD_STATUSES = {"golden", "approved"}
BAD_STATUSES = {"rejected"}
INTERESTING_STATUSES = list(GOOD_STATUSES | BAD_STATUSES)

MIN_SCORE_GAP_TIER_A = 1   # Gemini/ELYZAの平均スコア差がこれ未満ならノイズとして除外
CHOSEN_SCORE_MIN = 4       # user_feedbacks Tier B: これ以上をChosen候補
REJECTED_SCORE_MAX = 2     # user_feedbacks Tier B: これ以下 かつ bad評価ありをRejected候補

USER_FEEDBACK_FETCH_LIMIT = 500

# persona_feature_plan_v3.md §5.3: 単一owner_uid/単一narrator_persona_version_idの
# user由来ペア全体に対する寄与上限(5%)。
CONTRIBUTION_CAP_RATIO = 0.05

PROMPT_TEMPLATE = "お題「{odai}」で、誰もが納得する大衆性を持った秀逸ななぞかけを作成してください。"


def _resolve_narrator_persona_owner_uid(db, persona_id, cache: dict) -> str | None:
    """narrator_personasドキュメントからowner_uidを引く(§5.3の自己評価除外・
    寄与上限フィルタで使う)。呼び出し元がcache辞書を使い回すことで、同一
    persona_idへの重複Firestore読み取りを避ける。
    """
    if not persona_id:
        return None
    if persona_id not in cache:
        snap = db.collection("narrator_personas").document(persona_id).get()
        cache[persona_id] = (snap.to_dict() or {}).get("owner_uid") if snap.exists else None
    return cache[persona_id]


def _init_firebase():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
    return firestore.client()


def _get_odai(data: dict) -> str:
    """AI生成(generate.py)は 'odai'、人間投稿(submission.py)は 'A_TITLE' にお題を保存する。"""
    return data.get("odai") or data.get("A_TITLE", "")


def _classify(status: str) -> str:
    if status in GOOD_STATUSES:
        return "good"
    if status in BAD_STATUSES:
        return "bad"
    return None


def _bucket_pairing(good_bucket: list, bad_bucket: list, source: str) -> list:
    """good/badバケットをシャッフルして横断ペアリングする(pair_type=cross_prompt)。

    §5.3の寄与上限フィルタはchosen(採用)側の語り手ペルソナに帰属させるため、
    good_bucketの各要素が持つnarrator_persona_id/version_id/owner_uid(存在する
    場合のみ、管理者キュレーション側のバケットはこれらのキーを持たない)を
    ペアへ引き継ぐ。"_"始まりの内部メタデータキーは最終出力の直前で除去される。
    """
    good_bucket = list(good_bucket)
    bad_bucket = list(bad_bucket)
    random.shuffle(good_bucket)
    random.shuffle(bad_bucket)
    pairs = []
    for good, bad in zip(good_bucket, bad_bucket):
        pairs.append({
            "prompt": PROMPT_TEMPLATE.format(odai=good["odai"]),
            "chosen": good["text"], "rejected": bad["text"],
            "source": source, "pair_type": "cross_prompt",
            "_chosen_narrator_persona_version_id": good.get("narrator_persona_version_id"),
            "_chosen_owner_uid": good.get("owner_uid"),
        })
    return pairs


# ------------------------------------------------------------
# タスク1: 管理者キュレーション(gemini_status / elyza_status)
# ------------------------------------------------------------
def fetch_admin_curated_docs(db) -> dict:
    """gemini_status または elyza_status が golden/approved/rejected のドキュメントをdoc_id別に集約する。"""
    seen = {}
    for field in ("gemini_status", "elyza_status"):
        docs = db.collection("nazokake_items").where(
            filter=FieldFilter(field, "in", INTERESTING_STATUSES)
        ).stream()
        for doc in docs:
            seen[doc.id] = doc
    return seen


def extract_admin_curation_pairs(db) -> list:
    """管理者キュレーション由来のChosen/Rejectedペアを抽出する。

    同一ドキュメント内でGemini/ELYZAの評価が両極端に分かれる場合はsame_prompt、
    片側のみキュレーション済みの場合はスコアバケットに積んでcross_promptとして横断ペアリングする。
    """
    curated_docs = fetch_admin_curated_docs(db)

    pairs = []
    good_bucket, bad_bucket = [], []

    for doc in curated_docs.values():
        data = doc.to_dict()
        odai = _get_odai(data)
        gemini_text = data.get("nazokake_text", "")
        elyza_text = data.get("nazokake_text_llmjp", "")

        gemini_class = _classify(data.get("gemini_status", "n/a")) if gemini_text else None
        elyza_class = _classify(data.get("elyza_status", "n/a")) if elyza_text else None

        if gemini_class and elyza_class and gemini_class != elyza_class:
            chosen, rejected = (gemini_text, elyza_text) if gemini_class == "good" else (elyza_text, gemini_text)
            pairs.append({
                "prompt": PROMPT_TEMPLATE.format(odai=odai),
                "chosen": chosen, "rejected": rejected,
                "source": "admin", "pair_type": "same_prompt",
            })
            continue

        if gemini_class == "good":
            good_bucket.append({"odai": odai, "text": gemini_text})
        elif gemini_class == "bad":
            bad_bucket.append({"odai": odai, "text": gemini_text})

        if elyza_class == "good":
            good_bucket.append({"odai": odai, "text": elyza_text})
        elif elyza_class == "bad":
            bad_bucket.append({"odai": odai, "text": elyza_text})

    pairs.extend(_bucket_pairing(good_bucket, bad_bucket, source="admin"))
    return pairs


# ------------------------------------------------------------
# タスク2: user_feedbacks の統合
# ------------------------------------------------------------
def fetch_recent_user_feedbacks(db, limit: int = USER_FEEDBACK_FETCH_LIMIT) -> list:
    query = db.collection("user_feedbacks").order_by(
        "created_at", direction=firestore.Query.DESCENDING
    ).limit(limit)
    return [doc.to_dict() for doc in query.stream()]


def _fetch_nazokake_items_by_ids(db, doc_ids: list) -> dict:
    """db.get_all() でnazokake_itemsを一括取得する(doc_id件数分の個別get()を避ける)。"""
    if not doc_ids:
        return {}
    refs = [db.collection("nazokake_items").document(doc_id) for doc_id in doc_ids]
    return {snap.id: snap.to_dict() for snap in db.get_all(refs) if snap.exists}


def extract_user_feedback_pairs(db, limit: int = USER_FEEDBACK_FETCH_LIMIT) -> list:
    """user_feedbacks由来のChosen/Rejectedペアを抽出する(Tier A優先、Tier Bで補完)。

    §5.3: 各フィードバックについて、対象なぞかけを生んだ語り手ペルソナの
    owner_uidを引き、フィードバック投稿者(user_uid)と一致する場合は
    「自己評価」として集計対象から除外する(自己強化バイアス防止)。
    """
    feedbacks = fetch_recent_user_feedbacks(db, limit)
    if not feedbacks:
        return []

    doc_ids = sorted({fb["doc_id"] for fb in feedbacks if fb.get("doc_id")})
    items_by_id = _fetch_nazokake_items_by_ids(db, doc_ids)
    owner_uid_cache: dict = {}

    by_doc_scores = defaultdict(lambda: defaultdict(list))
    scored_entries = []  # (doc_id, model_target, overall_score, axis_feedback)
    self_eval_excluded = 0

    for fb in feedbacks:
        doc_id = fb.get("doc_id")
        model_target = fb.get("model_target")
        overall_score = fb.get("overall_score")
        if not doc_id or model_target not in ("gemini", "elyza") or overall_score is None:
            continue
        if doc_id not in items_by_id:
            continue

        data = items_by_id[doc_id]
        persona_owner_uid = _resolve_narrator_persona_owner_uid(
            db, data.get("narrator_persona_id"), owner_uid_cache
        )
        fb_user_uid = fb.get("user_uid")
        if fb_user_uid and persona_owner_uid and fb_user_uid == persona_owner_uid:
            self_eval_excluded += 1
            continue

        by_doc_scores[doc_id][model_target].append(overall_score)
        scored_entries.append((doc_id, model_target, overall_score, fb.get("axis_feedback") or {}))

    if self_eval_excluded:
        print(f"🛡️ [自己評価除外] user_feedbacks {self_eval_excluded}件を自己評価として除外しました。")

    pairs = []
    tier_a_doc_ids = set()

    # --- Tier A: 同一doc_id内でのGemini/ELYZA比較 ---
    for doc_id, by_model in by_doc_scores.items():
        if "gemini" not in by_model or "elyza" not in by_model:
            continue
        gemini_avg = sum(by_model["gemini"]) / len(by_model["gemini"])
        elyza_avg = sum(by_model["elyza"]) / len(by_model["elyza"])
        if abs(gemini_avg - elyza_avg) < MIN_SCORE_GAP_TIER_A:
            continue

        data = items_by_id[doc_id]
        odai = _get_odai(data)
        gemini_text = data.get("nazokake_text", "")
        elyza_text = data.get("nazokake_text_llmjp", "")
        if not gemini_text or not elyza_text:
            continue

        chosen, rejected = (gemini_text, elyza_text) if gemini_avg > elyza_avg else (elyza_text, gemini_text)
        pairs.append({
            "prompt": PROMPT_TEMPLATE.format(odai=odai),
            "chosen": chosen, "rejected": rejected,
            "source": "user", "pair_type": "same_prompt",
            "_chosen_narrator_persona_version_id": data.get("narrator_persona_version_id"),
            "_chosen_owner_uid": _resolve_narrator_persona_owner_uid(
                db, data.get("narrator_persona_id"), owner_uid_cache
            ),
        })
        tier_a_doc_ids.add(doc_id)

    # --- Tier B: スコアバケットによる横断比較(Tier Aで使用済みのdoc_idは二重計上しない) ---
    good_bucket, bad_bucket = [], []
    for doc_id, model_target, overall_score, axis_feedback in scored_entries:
        if doc_id in tier_a_doc_ids:
            continue
        data = items_by_id[doc_id]
        odai = _get_odai(data)
        text = data.get("nazokake_text" if model_target == "gemini" else "nazokake_text_llmjp", "")
        if not text:
            continue

        if overall_score >= CHOSEN_SCORE_MIN:
            good_bucket.append({
                "odai": odai, "text": text,
                "narrator_persona_version_id": data.get("narrator_persona_version_id"),
                "owner_uid": _resolve_narrator_persona_owner_uid(
                    db, data.get("narrator_persona_id"), owner_uid_cache
                ),
            })
        elif overall_score <= REJECTED_SCORE_MAX and "bad" in axis_feedback.values():
            bad_bucket.append({"odai": odai, "text": text})

    pairs.extend(_bucket_pairing(good_bucket, bad_bucket, source="user"))
    return pairs


# ------------------------------------------------------------
# タスク3: 合成・重複排除・出力
# ------------------------------------------------------------
def _dedupe(pairs: list) -> list:
    seen = set()
    result = []
    for p in pairs:
        key = (p["prompt"], p["chosen"], p["rejected"])
        if key in seen:
            continue
        seen.add(key)
        result.append(p)
    return result


def _apply_contribution_caps(pairs: list, cap_ratio: float = CONTRIBUTION_CAP_RATIO) -> list:
    """§5.3: user由来ペア(source=="user")について、単一owner_uid・単一
    narrator_persona_version_idのいずれかがuser由来ペア全体のcap_ratio(既定5%)を
    超えて寄与しないようサンプリングする。

    管理者キュレーション(source=="admin")は人間の審査ゲートを既に通過している
    ため対象外(計画書の表: 「管理者キュレーション(Task1) | 人間のゲートがある
    ため上限不要」)。属人化の実体はchosen(採用)側にあるとみなし、
    _chosen_owner_uid/_chosen_narrator_persona_version_idで判定する(DPOは
    chosen分布を強化する学習のため)。owner_uid/version_idが不明(None)の
    ペアは上限判定の対象外とする(判定材料が無いものまで恣意的に間引かない)。
    """
    admin_pairs = [p for p in pairs if p.get("source") != "user"]
    user_pairs = [p for p in pairs if p.get("source") == "user"]
    if not user_pairs:
        return pairs

    base_count = len(user_pairs)
    max_per_key = max(1, math.floor(cap_ratio * base_count))

    shuffled = list(user_pairs)
    random.shuffle(shuffled)

    owner_counts: dict = defaultdict(int)
    version_counts: dict = defaultdict(int)
    kept = []
    dropped = 0
    for pair in shuffled:
        owner_uid = pair.get("_chosen_owner_uid")
        version_id = pair.get("_chosen_narrator_persona_version_id")
        if owner_uid and owner_counts[owner_uid] >= max_per_key:
            dropped += 1
            continue
        if version_id and version_counts[version_id] >= max_per_key:
            dropped += 1
            continue
        if owner_uid:
            owner_counts[owner_uid] += 1
        if version_id:
            version_counts[version_id] += 1
        kept.append(pair)

    if dropped:
        print(
            f"🛡️ [寄与上限] user由来{base_count}件中{dropped}件を上限超過のため除外しました"
            f"(1owner_uid/1version_idあたり最大{max_per_key}件、cap_ratio={cap_ratio})。"
        )

    return admin_pairs + kept


def extract_dpo_dataset_v7():
    db = _init_firebase()

    print("🚀 [管理者キュレーション] gemini_status/elyza_status からペアを抽出中...")
    admin_pairs = extract_admin_curation_pairs(db)
    print(f"📊 管理者キュレーション由来: {len(admin_pairs)}件")

    print("🚀 [user_feedbacks] ユーザーフィードバックからペアを抽出中...")
    user_pairs = extract_user_feedback_pairs(db)
    print(f"📊 user_feedbacks由来: {len(user_pairs)}件")

    dpo_dataset = _dedupe(admin_pairs + user_pairs)
    print(f"📊 重複排除後の合計: {len(dpo_dataset)}件")

    dpo_dataset = _apply_contribution_caps(dpo_dataset)
    print(f"📊 寄与上限フィルタ後の合計: {len(dpo_dataset)}件")

    output_dir = Path.cwd() / "data"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "dpo_dataset.jsonl"

    # "_"始まりのキーは寄与上限フィルタ用の内部メタデータであり、既存の出力契約
    # (prompt/chosen/rejected/source/pair_type)には含めない。
    output_dataset = [
        {k: v for k, v in item.items() if not k.startswith("_")} for item in dpo_dataset
    ]

    with open(output_path, "w", encoding="utf-8") as f:
        for item in output_dataset:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"✅ DPO用データ抽出完了: {len(output_dataset)}件のペアを {output_path} に保存しました。")


if __name__ == "__main__":
    extract_dpo_dataset_v7()

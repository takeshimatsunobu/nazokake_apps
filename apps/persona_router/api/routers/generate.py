"""
api/routers/generate.py
==========================
POST /v1/generate: Step1(キャッシュ確認/推論) → Step2(分岐・生成) → Firestore保存を
同期的に処理して結果を返すエンドポイント。

【設計方針】
既存の apps/evaluator/backend とは異なり、この新サービスはLocal-First
(ローカルSQLiteが正でFirestoreは一方向バックアップ)の前提を採用しない。
Firestoreへ直接・同期的に読み書きする、状態を持たないCloud Runサービスとして
設計する(要件で明示された「同期的に処理して結果を返す」に合わせるため)。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from models.schemas import GenerateRoutedRequest, GenerateRoutedResponse
from nazokake_core.personas import get_personas
from services.penalty import build_blocked_response, check_block_status, record_route_b
from services.step1_cache import get_cached_step1, put_step1_cache
from services.step1_estimation import estimate_step1
from services.step2_generation import generate_step2

router = APIRouter()

# 正常系(ルートA)・異常系(ルートB)ともに、生成結果は同じコレクションへ保存する
# (要件2)。異常系は is_valid_for_training=false を必ず付与し、学習データ抽出
# バッチ(apps/evaluator/backend/scripts/extract_*.py 相当)側で除外できるようにする。
RESULTS_COLLECTION = "nazokake_results"


@router.post("/v1/generate", response_model=GenerateRoutedResponse)
async def generate_routed(req: GenerateRoutedRequest, db=Depends(get_db)):
    # --- 段階的ブロックの事前チェック(最優先。Step1/Step2のLLM呼び出しより前に
    # 必ず行う。荒らしユーザーに対してAPI課金を発生させ続けないための設計) ---
    block_status = check_block_status(db, req.client_uuid)
    if block_status.blocked:
        toku, kokoro, nazokake_text = build_blocked_response(req.odai, block_status.blocked_until)
        return GenerateRoutedResponse(
            doc_id="",
            odai=req.odai,
            persona_id=req.persona_id,
            route="BLOCKED",
            toku=toku,
            kokoro=kokoro,
            nazokake_text=nazokake_text,
            is_valid_for_training=False,
            step1_cache_hit=False,
            blocked_until=block_status.blocked_until,
        )

    # 【Phase4】ハードコードのPERSONASを直接参照する代わりにget_personas(db)を
    # 呼ぶことで、管理コクピット(Ⅳ生成設定ペイン)からの動的上書きを自動的に
    # 反映する(TTLキャッシュ済み、詳細はnazokake_core/personas.py参照)。
    persona = get_personas(db).get(req.persona_id)
    if persona is None:
        raise HTTPException(status_code=400, detail=f"不明なpersona_id: {req.persona_id}")

    # --- Step1: キャッシュ確認 → ミス時のみLLM推定 ---
    step1 = get_cached_step1(db, req.odai)
    step1_cache_hit = step1 is not None
    if step1 is None:
        # 【Phase3】コスト計装の追加に伴いasync化(services/step1_estimation.py参照)。
        step1, estimator_model_id = await estimate_step1(req.odai)
        put_step1_cache(db, req.odai, step1, estimator_model_id)

    # --- Step2: ルート決定(step1.is_valid_input)・生成・全文組み立てはこの関数の内部で行う ---
    # 【Phase3】コスト計装の追加に伴いasync化(services/step2_generation.py参照)。
    route, toku, kokoro, nazokake_text, generator_model_id = await generate_step2(
        req.odai, step1, persona, db=db
    )

    # --- 段階的ブロック: ルートB(異常入力)発生をカウントする ---
    # ここで新たな段階(5回ごと)に到達してもblocked_untilは「次回以降」の
    # リクエストから効き始める(今回の生成・保存はそのまま正常に完了させる)。
    if route == "B":
        record_route_b(db, req.client_uuid)

    # --- Firestore保存(正常系・異常系とも同一コレクション) ---
    doc_id = uuid.uuid4().hex
    doc = {
        "doc_id": doc_id,
        "odai": req.odai,
        "persona_id": req.persona_id,
        # 【Phase2追加】管理コクピットの直談判レビュー(apps/evaluator/backend/
        # api/routers/admin_review.py)が「このクライアントが何を書いてブロック
        # されたか(犯行現場)」をapi/routers/unlock.py::submit_unlock_request()から
        # 逆引きできるようにするための紐付けキー。生成時点では既存の挙動に一切
        # 影響しない(追記のみ)。
        "client_uuid": req.client_uuid,
        "route": route,
        "toku": toku,
        "kokoro": kokoro,
        "nazokake_text": nazokake_text,
        "is_valid_for_training": route == "A",
        "step1_cache_hit": step1_cache_hit,
        "step1_snapshot": step1.model_dump(),
        "generator_model_id": generator_model_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        # api/routers/timeline.pyの「座布団」リアクション用カウンタ。0始まり。
        "zabuton_count": 0,
    }
    db.collection(RESULTS_COLLECTION).document(doc_id).set(doc)

    return GenerateRoutedResponse(
        doc_id=doc_id,
        odai=req.odai,
        persona_id=req.persona_id,
        route=route,
        toku=toku,
        kokoro=kokoro,
        nazokake_text=nazokake_text,
        is_valid_for_training=doc["is_valid_for_training"],
        step1_cache_hit=step1_cache_hit,
    )

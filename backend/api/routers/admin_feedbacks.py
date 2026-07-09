"""管理者向けフィードバック集計ルーター(Phase 4 Step 3)。

GET /feedbacks : user_feedbacks コレクションから直近のフィードバックを取得する。
model_target / overall_score のクエリパラメータで絞り込み可能。
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends
from firebase_admin import firestore

from api.deps import get_db, verify_admin_token, handle_exceptions
from services.generation import refresh_fewshot_pool_from_feedback
from services.feedback_analyzer import (
    analyze_axis_divergence,
    generate_correction_prompt,
)
from services.evaluation import update_dynamic_correction_prompt

router = APIRouter()


def _fetch_feedbacks_sync(
    db, limit: int, model_target: Optional[str], overall_score: Optional[int]
) -> list:
    """Firestoreのstream()を同期的に実行し、リスト化して返すヘルパー関数。

    model_target/overall_score でのフィルタ + created_at ソートを組み合わせる場合、
    Firestore側に複合インデックスが必要になることがある(firestore.indexes.json参照)。
    """
    query = db.collection("user_feedbacks")
    if model_target:
        query = query.where("model_target", "==", model_target)
    if overall_score is not None:
        query = query.where("overall_score", "==", overall_score)
    query = query.order_by("created_at", direction=firestore.Query.DESCENDING).limit(
        limit
    )
    return list(query.stream())


@router.get("/feedbacks")
@handle_exceptions
async def get_admin_feedbacks(
    limit: int = 50,
    model_target: Optional[str] = None,
    overall_score: Optional[int] = None,
    db=Depends(get_db),
    admin_token: dict = Depends(verify_admin_token),
):
    docs = await asyncio.to_thread(
        _fetch_feedbacks_sync, db, limit, model_target, overall_score
    )
    return [doc.to_dict() for doc in docs]


@router.post("/feedbacks/refresh-fewshot")
@handle_exceptions
async def refresh_fewshot_pool(
    db=Depends(get_db),
    admin_token: dict = Depends(verify_admin_token),
):
    """稼働中のAPIサーバー自身のプロセス内で Few-shot プールと評価プロンプトの動的補正を更新する(Webhook方式)。

    別プロセスのバッチスクリプトからDBへ直接書き込んでも、このサーバーの
    services.generation._FEWSHOT_POOL / services.evaluation._DYNAMIC_CORRECTION_PROMPT
    (いずれもプロセス内メモリ)には反映されない(プロセス間でメモリを共有しないため)。
    このエンドポイントを外部から叩かせることで、両方の更新を確実にサーバー自身の
    プロセス内で実行させる。
    """
    added = await refresh_fewshot_pool_from_feedback(db)

    analysis = await analyze_axis_divergence(db)
    correction_prompt = generate_correction_prompt(analysis)
    update_dynamic_correction_prompt(correction_prompt)

    return {"status": "success", "added": added, "correction_prompt": correction_prompt}

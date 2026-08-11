"""管理者向けフィードバック集計ルーター(Phase 4 Step 3)。

GET /feedbacks : user_feedbacks コレクションから直近のフィードバックを取得する。
model_target / overall_score のクエリパラメータで絞り込み可能。
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends
from firebase_admin import firestore

from api.deps import get_db, verify_admin_token, handle_exceptions
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
    """稼働中のAPIサーバー自身のプロセス内で、評価プロンプトの動的補正を更新する(Webhook方式)。

    【Phase5/6】Few-shotプールの強制更新はこのエンドポイントの責務では
    なくなった。管理コクピットの「⭐ Few-shot採用」確定時にFirestore
    (nazokake_fewshots)へ即時Pushされ、生成側は
    nazokake_core.fewshots.get_fewshot_pool()のTTLキャッシュ(既定300秒)経由で
    自動的に反映を受け取るため、手動リフレッシュ操作が不要になった
    (旧_FEWSHOT_POOLはプロセス内メモリのみで複数ワーカー間に伝播しない欠陥が
    あったが、Firestore経由の共有プールへ統一したことで解消している)。
    このエンドポイント自体は評価プロンプトの動的補正(_DYNAMIC_CORRECTION_PROMPT)
    の更新用途で引き続き有効。
    """
    analysis = await analyze_axis_divergence(db)
    correction_prompt = generate_correction_prompt(analysis)
    update_dynamic_correction_prompt(correction_prompt)

    return {"status": "success", "correction_prompt": correction_prompt}

"""ユーザーフィードバック受付ルーター(Phase 4: 自己進化ループの入力口)。

POST /nazokake/{doc_id}/feedback : 生成物に対するユーザー評価を user_feedbacks に記録する。
"""

import asyncio
import html

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db, verify_user_token, handle_exceptions
from models.schemas import UserFeedbackRequest
from nazokake_core.schemas import UserFeedback

router = APIRouter()


@router.post("/nazokake/{doc_id}/feedback")
@handle_exceptions
async def submit_user_feedback(
    doc_id: str,
    req: UserFeedbackRequest,
    db=Depends(get_db),
    decoded_token: dict = Depends(verify_user_token),
):
    doc_ref = db.collection("nazokake_items").document(doc_id)
    doc = await asyncio.to_thread(doc_ref.get)
    if not doc.exists:
        raise HTTPException(status_code=404, detail="対象のなぞかけが見つかりません")

    feedback = UserFeedback(
        doc_id=doc_id,
        user_uid=decoded_token.get("uid", "unknown"),
        overall_score=req.overall_score,
        axis_feedback=req.axis_feedback,
        comment=html.escape(req.comment.strip()),
        model_target=req.model_target,
    )
    await asyncio.to_thread(
        db.collection("user_feedbacks").document().set, feedback.model_dump()
    )
    return {"status": "success"}

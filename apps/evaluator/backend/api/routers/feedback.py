"""ご意見箱ルーター（DDD再編で endpoints.py から切り出し）。

POST /feedback : アプリへのフィードバックを app_feedbacks に記録する。
admin_db グローバル参照を廃し、Depends(get_db) で DI する。
"""

import html

from fastapi import APIRouter, Depends
from firebase_admin import firestore

from api.deps import get_db, handle_exceptions
from models.schemas import FeedbackRequest

router = APIRouter()


@router.post("/feedback")
@handle_exceptions
def submit_feedback(req: FeedbackRequest, db=Depends(get_db)):
    clean_comment = html.escape(str(req.comment or "").strip())
    db.collection("app_feedbacks").document().set(
        {
            "score": req.score,
            "comment": clean_comment,
            "user_slug": req.user_slug,
            "status": 0,
            "created_at": firestore.SERVER_TIMESTAMP,
        }
    )
    return {"status": "success"}

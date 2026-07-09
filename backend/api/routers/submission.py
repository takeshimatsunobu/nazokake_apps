"""投稿関連ルーター（DDD再編で endpoints.py から切り出し）。

POST /submit_human : 人間が作成したなぞかけを登録し、AI評価タスクを起動する。
admin_db グローバル参照を廃し、Depends(get_db) で DI する。
"""

import asyncio
import random
from fastapi import APIRouter, Depends
from firebase_admin import firestore

from api.deps import get_db, handle_exceptions
from models.schemas import HumanSubmitRequest
from services.evaluation import run_evaluation

router = APIRouter()


@router.post("/submit_human")
@handle_exceptions
async def submit_human(req: HumanSubmitRequest, db=Depends(get_db)):
    doc_ref = db.collection("nazokake_items").document()
    doc_ref.set(
        {
            "A_TITLE": req.odai,
            "nazokake_text": req.nazokake_text,
            "author": "Human",
            "parent_id": req.parent_id,
            "is_sft_data": bool(req.parent_id),
            "timestamp": firestore.SERVER_TIMESTAMP,
            "status": "processing",
            "eval_status": "processing",
            "s_total": 0.0,
            "random_weight": random.random(),
        }
    )
    # run_evaluation は評価のみを返す(旧evaluate_and_update_taskと異なりDB更新は行わない)ため、
    # generate.py の process_gemini と同じパターンでここに書き込み責務を持たせる。
    try:
        ev = await run_evaluation(req.odai, req.nazokake_text)
        await asyncio.to_thread(
            doc_ref.update,
            {
                "scores": ev["scores"],
                "s_total": ev["s_total"],
                "axis_comments": ev["axis_comments"],
                "overall": ev["overall"],
                "eval_status": "completed",
                "feed_ready": True,
                "status": "all_completed",
            },
        )
    except Exception as e:
        await asyncio.to_thread(
            doc_ref.update,
            {
                "status": "error",
                "eval_status": "error",
                "message": f"評価に失敗しました: {e}",
            },
        )
    return {"status": "processing", "doc_id": doc_ref.id}

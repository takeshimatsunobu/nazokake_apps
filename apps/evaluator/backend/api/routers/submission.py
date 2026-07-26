"""投稿関連ルーター（DDD再編で endpoints.py から切り出し）。

POST /submit_human : 人間が作成したなぞかけを登録し、AI評価タスクを起動する。

【Local-First】永続化先はFirestoreではなくローカルSQLite(nazokake_core.database)。
各 async_upsert_item() 呼び出しは単発のDB往復であり、run_evaluation(LLM推論)の
実行中はDB接続を保持しない(generate.pyのprocess_gemini と同じパターン)。
"""

import random
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks

from api.deps import handle_exceptions
from models.schemas import HumanSubmitRequest
from nazokake_core.database import async_upsert_item
from nazokake_core.firestore_sync import sync_once_safe
from services.evaluation import run_evaluation

router = APIRouter()


@router.post("/submit_human")
@handle_exceptions
async def submit_human(req: HumanSubmitRequest, background_tasks: BackgroundTasks):
    doc_id = uuid.uuid4().hex
    await async_upsert_item({
        "doc_id": doc_id,
        "odai": req.odai,
        "nazokake_text": req.nazokake_text,
        "author": "Human",
        "parent_id": req.parent_id,
        "is_sft_data": bool(req.parent_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "processing",
        "eval_status": "processing",
        "s_total": 0.0,
        "random_weight": random.random(),  # noqa: S311 (無限スクロール用シーク乱数。暗号用途ではない)
    })
    # run_evaluation は評価のみを返す(旧evaluate_and_update_taskと異なりDB更新は行わない)ため、
    # generate.py の process_gemini と同じパターンでここに書き込み責務を持たせる。
    try:
        ev = await run_evaluation(req.odai, req.nazokake_text)
        await async_upsert_item({
            "doc_id": doc_id,
            "scores": ev["scores"],
            "s_total": ev["s_total"],
            "axis_comments": ev["axis_comments"],
            "overall": ev["overall"],
            "eval_status": "completed",
            "feed_ready": True,
            "status": "all_completed",
        })
    except Exception as e:
        await async_upsert_item({
            "doc_id": doc_id,
            "status": "error",
            "eval_status": "error",
            "message": f"評価に失敗しました: {e}",
        })
    # instructions/239: Cloud Run上のSQLiteはエフェメラルなため、一連の書き込み完了後に
    # Firestoreへのバックアップ同期をBackgroundTasksで試みる(レスポンスをブロックしない)。
    background_tasks.add_task(sync_once_safe)
    return {"status": "processing", "doc_id": doc_id}

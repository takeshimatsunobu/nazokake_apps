"""フィード関連ルーター（DDD再編で endpoints.py から切り出し）。
GET  /feed/items              : 真のランダム作品フィード（案C: 乱数フィールドハック）
GET  /feed/golden             : ゴールデン作品フィード
POST /feed/evaluate/{doc_id}  : ユーザーによる作品の評価・添削

【Local-First】永続化先はFirestoreではなく packages/shared_core/nazokake_core/database.py の
ローカルSQLite。async_get_feed_items/async_get_golden_feed_items/async_get_item/
async_append_human_evaluation はいずれも短命な単発DB往復であり、Firestore通信は行わない。

【絶対制約】返却データはローカルDBの status/feed_ready 等のみを正としており、クラウドへの
同期状態(sync_status)は描画のブロック条件として一切使わない(database.py側で
_row_to_ui_dict がsync_status/last_sync_errorをレスポンスから除外している)。
"""

import html
from typing import Optional, Union
from fastapi import APIRouter, HTTPException, Request

from api.deps import handle_exceptions
from models.schemas import ErrorEnvelope, FeedItemsResponse, StatusResponse
from nazokake_core.database import (
    async_append_human_evaluation,
    async_get_feed_items,
    async_get_golden_feed_items,
    async_get_item,
)

router = APIRouter()


@router.get("/feed/items", response_model=Union[FeedItemsResponse, ErrorEnvelope])
@handle_exceptions
async def get_user_feed(last_doc_id: Optional[str] = None, limit: int = 5):
    # 💡 案C: 乱数フィールドハックの実装。カーソル無し(1バッチ目)のときのみ
    # 巡回シーク(wrap-around)フォールバックが有効になる(async_get_feed_items内部)。
    cursor_random_weight = None
    if last_doc_id:
        cursor_item = await async_get_item(last_doc_id)
        if cursor_item is not None:
            cursor_random_weight = cursor_item.get("random_weight")

    items = await async_get_feed_items(
        limit=limit, cursor_random_weight=cursor_random_weight
    )
    return {"items": items}


@router.get("/feed/golden", response_model=Union[FeedItemsResponse, ErrorEnvelope])
@handle_exceptions
async def get_golden_feed(last_doc_id: Optional[str] = None, limit: int = 5):
    cursor_created_at = None
    if last_doc_id:
        cursor_item = await async_get_item(last_doc_id)
        if cursor_item is not None:
            cursor_created_at = cursor_item.get("created_at")

    items = await async_get_golden_feed_items(
        limit=limit, cursor_created_at=cursor_created_at
    )
    return {"items": items}


@router.post("/feed/evaluate/{doc_id}", response_model=StatusResponse)
@handle_exceptions
async def evaluate_user_item(doc_id: str, request: Request):
    try:
        data = await request.json()
        odai = html.escape(str(data.get("odai", "") or "").strip())
        toku = html.escape(str(data.get("toku", "") or "").strip())
        kokoro = html.escape(str(data.get("kokoro", "") or "").strip())
        if len(odai) < 1 or len(toku) < 1 or len(kokoro) < 1:
            raise HTTPException(status_code=400, detail="入力が短すぎます")

        user_slug = data.get("user_slug", "anonymous")
        found = await async_append_human_evaluation(
            doc_id,
            evaluation_entry={
                "user_score": data.get("s_total", 0),
                "user_slug": user_slug,
            },
            comment_entry={
                "comment": data.get("human_comment", ""),
                "user_slug": user_slug,
            },
        )
        if not found:
            raise HTTPException(
                status_code=404, detail="対象のなぞかけが見つかりません"
            )
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

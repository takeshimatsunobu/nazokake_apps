"""フィード関連ルーター（DDD再編で endpoints.py から切り出し）。
GET  /feed/items              : 真のランダム作品フィード（案C: 乱数フィールドハック）
GET  /feed/golden             : ゴールデン作品フィード
POST /feed/evaluate/{doc_id}  : ユーザーによる作品の評価・添削（赤ペン）

【Local-First】永続化先はFirestoreではなく packages/shared_core/nazokake_core/database.py の
ローカルSQLite。async_get_feed_items/async_get_golden_feed_items/async_get_item/
async_append_human_evaluation/async_upsert_item はいずれも短命な単発DB往復であり、
Firestore通信は行わない。

【絶対制約】返却データはローカルDBの status/feed_ready 等のみを正としており、クラウドへの
同期状態(sync_status)は描画のブロック条件として一切使わない(database.py側で
_row_to_ui_dict がsync_status/last_sync_errorをレスポンスから除外している)。

【Phase5/6】POST /feed/evaluate/{doc_id} は、元の作品に対する評価専用だったが、
道場破りの「赤ペン」入力欄(odai/toku/kokoro)が実は一切永続化されていなかった
バグを修正するため、送信内容が元の作品と差分ありの場合は「赤ペン修正」とみなし
既存行を書き換えず新規行としてINSERTする(origin_type="user_akapen")。差分が
無い場合(星評価・コメントのみ)は従来通り既存行のhuman_evaluationsへ追記する。
"""

import html
import uuid
from datetime import datetime, timezone
from typing import Optional, Union
from fastapi import APIRouter, HTTPException, Request

from api.deps import handle_exceptions
from models.schemas import ErrorEnvelope, FeedItemsResponse, StatusResponse
from nazokake_core.database import (
    async_append_human_evaluation,
    async_get_feed_items,
    async_get_golden_feed_items,
    async_get_item,
    async_upsert_item,
)
from services.toku_kokoro import build_nazokake_text, extract_toku_kokoro

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
        evaluation_entry = {"user_score": data.get("s_total", 0), "user_slug": user_slug}
        comment_entry = {"comment": data.get("human_comment", ""), "user_slug": user_slug}

        original = await async_get_item(doc_id)
        if original is None:
            raise HTTPException(status_code=404, detail="対象のなぞかけが見つかりません")

        orig_odai = html.escape(str(original.get("odai") or "").strip())
        orig_toku_raw, orig_kokoro_raw = extract_toku_kokoro(original)
        orig_toku = html.escape(orig_toku_raw)
        orig_kokoro = html.escape(orig_kokoro_raw)

        is_correction = odai != orig_odai or toku != orig_toku or kokoro != orig_kokoro

        if is_correction:
            # 【Phase5/6: 赤ペン未保存バグの修正】添削内容(odai/toku/kokoro)は
            # 元の作品を書き換えず、新規行としてINSERTする(review_status=NULLの
            # まま保存され、管理コクピットの承認待ちキューへ自動的に乗る)。
            new_doc_id = uuid.uuid4().hex
            await async_upsert_item(
                {
                    "doc_id": new_doc_id,
                    "odai": odai,
                    "result": {"toku": toku, "kokoro": kokoro},
                    "nazokake_text": build_nazokake_text(odai, toku, kokoro),
                    "origin_type": "user_akapen",
                    "source_item_id": doc_id,
                    "review_status": None,
                    # trend-queue(claim_pending_trend)の対象に紛れ込ませないための
                    # センチネル値(statusのORM既定値"pending"を明示的に上書き)。
                    "status": "n/a",
                    "gemini_status": "n/a",
                    "elyza_status": "n/a",
                    "feed_ready": False,
                    "is_user_edited": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "human_evaluations": [{**evaluation_entry, **comment_entry}],
                }
            )
        else:
            found = await async_append_human_evaluation(
                doc_id, evaluation_entry=evaluation_entry, comment_entry=comment_entry
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

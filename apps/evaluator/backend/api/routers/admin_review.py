"""api/routers/admin_review.py
================================
Ⅱ ユーザーの投稿に基づく評価・承認(Phase2)。

- GET  /unlock-requests                      : status=="pending"の直談判一覧
  (apps/persona_router が所有するFirestoreコレクションを直接読む。詳細は
  services/unlock_review.py のモジュールdocstring参照)。
- POST /unlock-requests/{request_id}/action  : 赦す(pardon)/リセット(reset)/却下(reject)。
- POST /nazokake-items/{doc_id}/fewshot      : Few-shot採用フラグ+評価軸タグの更新。
  「承認待ちデータ」「RLHFレビュー」の両カードから共通で呼ばれる(どちらも最終的には
  同じnazokake_itemsの1行を指すため)。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore
from google.api_core.exceptions import FailedPrecondition
from google.cloud.firestore_v1.base_query import FieldFilter

from api.deps import get_db, handle_exceptions, verify_admin_token
from models.schemas import (
    FewshotUpdateRequest,
    FewshotUpdateResponse,
    UnlockActionRequest,
    UnlockActionResponse,
    UnlockRequestListResponse,
)
from nazokake_core.database import async_append_audit_log, async_get_item, async_upsert_item
from services.unlock_review import pardon, reject, reset

router = APIRouter()

UNLOCK_REQUESTS_COLLECTION = "unlock_requests"


def _fetch_pending_unlock_requests_sync(db) -> tuple[list[dict], str | None]:
    """直談判一覧を取得する。

    【防御的実装】status(等価)+created_at(orderBy)の組み合わせはFirestoreの
    複合インデックスを要求する。未作成の場合 google.api_core.exceptions.
    FailedPrecondition (HTTP 400 "The query requires an index...") が飛んでくる。
    これを本関数の外へ伝播させると、@handle_exceptionsが返す汎用エラー封筒
    ({"status":"error","message":...})がUnlockRequestListResponse(itemsが必須)
    のバリデーションに失敗し、FastAPIのResponseValidationErrorという「二重の
    500」に化けてブラウザにはCORSエラーとして見える(実際に発生した障害)。
    そのため例外はここで確実に捕捉し、空配列+警告メッセージという
    スキーマ適合済みの結果へ変換してから返す。
    """
    query = (
        db.collection(UNLOCK_REQUESTS_COLLECTION)
        .where(filter=FieldFilter("status", "==", "pending"))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
    )
    try:
        return [d.to_dict() for d in query.stream()], None
    except FailedPrecondition as e:
        warning = (
            "Firestoreの複合インデックス(unlock_requests: status + created_at)が"
            f"未作成のため、直談判一覧を取得できませんでした。エラーメッセージ内の"
            f"URLからインデックスを作成してください。詳細: {e}"
        )
        print(f"⚠️ [admin_review] {warning}")
        return [], warning
    except Exception as e:
        warning = f"直談判一覧の取得中に予期しないエラーが発生しました: {e}"
        print(f"⚠️ [admin_review] {warning}")
        return [], warning


@router.get("/unlock-requests", response_model=UnlockRequestListResponse)
@handle_exceptions
async def get_unlock_requests(
    admin_token: dict = Depends(verify_admin_token), db=Depends(get_db)
):
    items, warning = await asyncio.to_thread(_fetch_pending_unlock_requests_sync, db)
    return {"items": items, "warning": warning}


@router.post("/unlock-requests/{request_id}/action", response_model=UnlockActionResponse)
@handle_exceptions
async def apply_unlock_action(
    request_id: str,
    req: UnlockActionRequest,
    admin_token: dict = Depends(verify_admin_token),
    db=Depends(get_db),
):
    doc_ref = db.collection(UNLOCK_REQUESTS_COLLECTION).document(request_id)
    snapshot = await asyncio.to_thread(doc_ref.get)
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="対象の直談判が見つかりません")

    data = snapshot.to_dict() or {}
    if data.get("status") != "pending":
        raise HTTPException(status_code=409, detail="この直談判は既に処理済みです")

    admin_uid = admin_token.get("uid", "unknown")

    if req.action == "pardon":
        client_uuid = data.get("client_uuid")
        if not client_uuid:
            raise HTTPException(status_code=422, detail="対象のclient_uuidが記録されていません")
        await pardon(db, client_uuid, request_id, admin_uid)
    elif req.action == "reset":
        client_uuid = data.get("client_uuid")
        if not client_uuid:
            raise HTTPException(status_code=422, detail="対象のclient_uuidが記録されていません")
        await reset(db, client_uuid, request_id, admin_uid)
    else:
        await reject(db, request_id, admin_uid)

    return UnlockActionResponse(status="success", request_id=request_id, action=req.action)


@router.post("/nazokake-items/{doc_id}/fewshot", response_model=FewshotUpdateResponse)
@handle_exceptions
async def update_fewshot_selection(
    doc_id: str,
    req: FewshotUpdateRequest,
    admin_token: dict = Depends(verify_admin_token),
):
    """「承認待ちデータ」「RLHFレビュー」双方のカードから共通で呼ばれる、Few-shot
    採用フラグ+評価軸タグの更新。実際にservices.generation._FEWSHOT_POOLへ
    動的に組み込む配線はPhase4(生成デフォルト設定のFirestore連携・キャッシュ基盤)で
    行う予定であり、本エンドポイントは判断そのものの永続化に留める。
    """
    existing = await async_get_item(doc_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="対象のなぞかけが見つかりません")

    await async_upsert_item(
        {
            "doc_id": doc_id,
            "is_fewshot_selected": req.is_fewshot_selected,
            "fewshot_axis_tag": req.fewshot_axis_tag if req.is_fewshot_selected else None,
        }
    )
    await async_append_audit_log(
        target_item_id=doc_id,
        actor=f"admin:{admin_token.get('uid', 'unknown')}",
        action="FEWSHOT_SELECT" if req.is_fewshot_selected else "FEWSHOT_UNSELECT",
        reason_dict={"fewshot_axis_tag": req.fewshot_axis_tag},
    )

    return FewshotUpdateResponse(status="success", doc_id=doc_id)

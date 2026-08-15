"""api/routers/unlock.py
=========================
POST /v1/unlock-requests: ブロック画面の「運営へ直談判する」フォーム送信。

【スコープ注記】このAPIはFirestore(unlock_requestsコレクション)への記録のみを
行う。実際のブロック解除(services/penalty.pyが見るuser_penalties.blocked_untilの
クリア)は運営が手動で行うことを想定し、本フェーズでは自動承認・自動解除の
ロジックは実装しない(要件で明示された「直談判」= 申し立てを届ける機能に限定)。

【Phase2追加: 「犯行現場」のスナップショット】管理コクピット(apps/evaluator/backend/
api/routers/admin_review.py)の直談判レビューが「このユーザーが何を書いて
ブロックされたか」を一目で確認できるよう、申し立て時点でこのclient_uuidの
直近ルートB(異常入力のエンタメ化)生成物をnazokake_resultsから逆引きし、
odai/nazokake_textをoffending_odai/offending_textとしてこのドキュメントへ
複製する(読み取り時にJOINを要求しない、blocked_until_snapshotと同じ設計思想)。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from api.deps import get_db
from models.schemas import UnlockRequestCreate, UnlockRequestResponse
from services.penalty import check_block_status

router = APIRouter()

UNLOCK_REQUESTS_COLLECTION = "unlock_requests"
RESULTS_COLLECTION = "nazokake_results"


def _find_offending_generation(db, client_uuid: str) -> tuple[str | None, str | None]:
    """このclient_uuidが直近に生成したルートB(異常入力)のodai/nazokake_textを
    返す(見つからなければ(None, None))。ブロックへ直結した「犯行現場」の
    近似として、created_at降順で最新の1件のみを対象とする。

    このクエリはFirestoreの複合インデックス(client_uuid等価 + route等価 +
    created_at範囲/ソート)を要求する可能性がある。見つからない場合(まだ
    ルートBを1度も引いていないのに直談判が送られてきた等の想定外の経路)は
    素直にNoneを返し、呼び出し元はoffending_odai/offending_textをnullのまま
    保存する(申し立てそのものは拒否しない)。
    """
    try:
        query = (
            db.collection(RESULTS_COLLECTION)
            .where(filter=FieldFilter("client_uuid", "==", client_uuid))
            .where(filter=FieldFilter("route", "==", "B"))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(1)
        )
        docs = list(query.stream())
        if not docs:
            return None, None
        data = docs[0].to_dict() or {}
        return data.get("odai"), data.get("nazokake_text")
    except Exception:
        # インデックス未作成等で失敗しても、直談判の受付自体は失敗させない
        # (offending_odai/offending_textが無いだけの劣化表示に留める)。
        return None, None


@router.post("/v1/unlock-requests", response_model=UnlockRequestResponse)
async def submit_unlock_request(req: UnlockRequestCreate, db=Depends(get_db)):
    # 申し立て時点のブロック状態をスナップショットとして残しておく(運営が
    # レビューする際、「本当にブロック中だったか」「いつ解除予定だったか」を
    # user_penalties側と突き合わせずにこのドキュメント単体で確認できるようにする)。
    block_status = check_block_status(db, req.client_uuid)
    offending_odai, offending_text = _find_offending_generation(db, req.client_uuid)

    request_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    db.collection(UNLOCK_REQUESTS_COLLECTION).document(request_id).set(
        {
            "request_id": request_id,
            "client_uuid": req.client_uuid,
            "message": req.message,
            "blocked_until_snapshot": block_status.blocked_until,
            "offending_odai": offending_odai,
            "offending_text": offending_text,
            "status": "pending",
            "created_at": now,
        }
    )

    return UnlockRequestResponse(request_id=request_id, submitted_at=now)

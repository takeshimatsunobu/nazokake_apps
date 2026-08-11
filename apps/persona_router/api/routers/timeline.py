"""
api/routers/timeline.py
==========================
GET /v1/timeline: 公開タイムラインのカーソルページネーション取得。
POST /v1/timeline/{doc_id}/zabuton: 「座布団」リアクションのインクリメント。

【なぜクライアント直接のFirestore読み取り(Firebase Web SDK)にしなかったか】
apps/evaluator/frontend の既存実装(api.js::apiFetchFeed → 自前バックエンドの
/feed/items)と同じ設計判断に揃えた。Firestoreへの読み書きはこのアプリでも
firebase_admin(サーバー側)経由のみに一本化し、クライアントからの直接アクセスを
許可するためのFirestore Security Rules変更を新たに必要としない(このアプリの
「Firestoreへの書き込みはbackend経由のみ」というSSoT原則を、読み取りにも
一貫して適用する)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore

from api.deps import get_db
from api.routers.generate import RESULTS_COLLECTION
from models.schemas import TimelineItem, TimelineResponse, ZabutonResponse

router = APIRouter()

DEFAULT_LIMIT = 20
MAX_LIMIT = 50

# TimelineItemはextra="forbid"(このアプリ共通の防衛的プログラミング規約)なので、
# Firestoreの生ドキュメント(step1_snapshot/generator_model_id等、タイムライン
# 表示に不要な内部フィールドも含む)をそのままmodel_validate()に渡すと必ず
# ValidationErrorになる。表示に必要なフィールドだけへ明示的に射影してから渡す。
_TIMELINE_FIELDS = (
    "doc_id",
    "odai",
    "persona_id",
    "route",
    "toku",
    "kokoro",
    "nazokake_text",
    "is_valid_for_training",
    "zabuton_count",
    "created_at",
)


def _to_timeline_item(data: dict) -> TimelineItem:
    # zabuton_count等、本フィールド追加より前に作成された旧ドキュメントには
    # キー自体が存在しないことがある。dictに含めず省略することで、Pydantic側の
    # デフォルト値(Field(0, ...))を正しく適用させる(Noneを明示的に渡すと
    # int型のバリデーションに失敗するため、in data判定で選別する)。
    projected = {k: data[k] for k in _TIMELINE_FIELDS if k in data}
    return TimelineItem.model_validate(projected)


@router.get("/v1/timeline", response_model=TimelineResponse)
async def get_timeline(before: str | None = None, limit: int = DEFAULT_LIMIT, db=Depends(get_db)):
    """新着順(created_at降順)でタイムラインを返す。

    before: 直前ページ最後の要素のcreated_at(ISO8601)。指定するとそれより
    古い項目から返す(無限スクロール用カーソル)。
    is_valid_for_training=falseの項目もあえて除外しない(モジュールdocstring参照)。
    表示可否・見せ方の制御はフロントエンドの責務。
    """
    safe_limit = max(1, min(limit, MAX_LIMIT))

    query = db.collection(RESULTS_COLLECTION).order_by(
        "created_at", direction=firestore.Query.DESCENDING
    )
    if before:
        query = query.where(filter=firestore.FieldFilter("created_at", "<", before))
    query = query.limit(safe_limit)

    docs = list(query.stream())
    items = [_to_timeline_item(d.to_dict() or {}) for d in docs]
    next_before = items[-1].created_at if len(items) == safe_limit else None

    return TimelineResponse(items=items, next_before=next_before)


@router.post("/v1/timeline/{doc_id}/zabuton", response_model=ZabutonResponse)
async def add_zabuton(doc_id: str, db=Depends(get_db)):
    """「座布団」リアクションを1件加算する。

    Phase2時点では連打・多重送信の防止はフロントエンド側(送信後ボタンを無効化
    し、反応済みdoc_idをlocalStorageへ記録)のみで行う。サーバー側のレート制限/
    重複排除は未実装(将来の悪用が問題化した場合に追加を検討する、と明記しておく)。
    """
    doc_ref = db.collection(RESULTS_COLLECTION).document(doc_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail=f"指定のdoc_idが見つかりません: {doc_id}")

    doc_ref.update({"zabuton_count": firestore.Increment(1)})
    updated = doc_ref.get().to_dict() or {}
    return ZabutonResponse(doc_id=doc_id, zabuton_count=updated.get("zabuton_count", 0))

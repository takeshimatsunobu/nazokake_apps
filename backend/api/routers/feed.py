"""フィード関連ルーター（DDD再編で endpoints.py から切り出し）。
GET  /feed/items              : 真のランダム作品フィード（案C: 乱数フィールドハック）
GET  /feed/golden             : ゴールデン作品フィード
POST /feed/evaluate/{doc_id}  : ユーザーによる作品の評価・添削

admin_db グローバル参照を廃し、Depends(get_db) で DI する。
※フィード取得は取得失敗時に {"items": []} を返す既存挙動を維持しつつ、開発環境用にデバッグエラーを付与。
@handle_exceptions は外側の安全網として付与する。
"""

import html
import asyncio
import random
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from google.cloud import firestore

from api.deps import get_db, serialize_doc, handle_exceptions

router = APIRouter()


def _fetch_docs_sync(query, limit):
    """Firestoreのstream()を同期的に実行し、リスト化して返すヘルパー関数"""
    return list(query.limit(limit).stream())


def _fetch_cursor_sync(db, doc_id):
    """Firestoreのドキュメントを同期的に取得するヘルパー関数"""
    return db.collection("nazokake_items").document(doc_id).get()


@router.get("/feed/items")
@handle_exceptions
async def get_user_feed(
    last_doc_id: Optional[str] = None, limit: int = 5, db=Depends(get_db)
):
    try:
        # 💡 案C: 乱数フィールドハックの実装
        # 1バッチ目の要求（last_doc_idなし）のときは、毎回フロントエンドの代わりにバックエンド側で
        # 0.0〜1.0 のランダムなシード基準値を生成して、インデックスのシーク開始位置を散らす
        seed_weight = random.random()

        # 基本クエリの構築（random_weightの昇順でソートするため、この複合インデックスが必要）
        query = (
            db.collection("nazokake_items")
            .where("feed_ready", "==", True)
            .where("is_user_edited", "==", False)
            .where("is_golden_data", "==", False)
        )

        if last_doc_id:
            # 2ページ目以降の無限スクロール時は、カーソルドキュメントの random_weight の直後からページング
            cursor_doc = await asyncio.to_thread(_fetch_cursor_sync, db, last_doc_id)
            if cursor_doc.exists:
                cursor_data = cursor_doc.to_dict() or {}
                # 万が一古いデータで random_weight が入っていない場合は通常のtimestampフォールバックに備える
                if "random_weight" in cursor_data:
                    query = query.order_by("random_weight").start_after(cursor_doc)
                else:
                    query = query.order_by(
                        "timestamp", direction=firestore.Query.DESCENDING
                    ).start_after(cursor_doc)
            else:
                query = query.order_by("random_weight").start_at([seed_weight])
        else:
            # 初回読み込み時は、ランダムなシード値以上の場所から昇順ソートで5件を撃ち抜く
            query = query.where("random_weight", ">=", seed_weight).order_by(
                "random_weight"
            )

        # クエリの実行(stream)を別スレッドで安全に非同期処理
        docs = await asyncio.to_thread(_fetch_docs_sync, query, limit)
        all_items = [serialize_doc(doc) for doc in docs]

        # 💡 フォールバック処理：もしランダムシード値が高すぎて（例: 0.99）
        # その上の範囲に5件未満しか残っていなかった場合、0.0 に戻して残りの必要件数をシームレスに回収する（巡回シーク）
        if len(all_items) < limit and not last_doc_id:
            needed = limit - len(all_items)
            fallback_query = (
                db.collection("nazokake_items")
                .where("feed_ready", "==", True)
                .where("is_user_edited", "==", False)
                .where("is_golden_data", "==", False)
                .where("random_weight", "<", seed_weight)
                .order_by("random_weight")
            )
            fallback_docs = await asyncio.to_thread(
                _fetch_docs_sync, fallback_query, needed
            )
            all_items.extend([serialize_doc(doc) for doc in fallback_docs])

        return {"items": all_items}

    except Exception as e:
        error_msg = str(e).lower()
        # 💡 改善：開発時にインデックスエラーの真因を握り潰さないよう、フロントに debug_error フラグを応答
        if "index" in error_msg or "precondition" in error_msg:
            print(f"⚠️ Feed Load Random Index Required: {e}")
            return {
                "items": [],
                "debug_error": "Index Required",
                "setup_url": "https://console.firebase.google.com/v1/r/project/nazokakeapp-137e5/firestore/indexes",
            }
        raise e


@router.get("/feed/golden")
@handle_exceptions
async def get_golden_feed(
    last_doc_id: Optional[str] = None, limit: int = 5, db=Depends(get_db)
):
    try:
        query = (
            db.collection("nazokake_items")
            .where("is_golden_data", "==", True)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
        )
        if last_doc_id:
            cursor_doc = await asyncio.to_thread(_fetch_cursor_sync, db, last_doc_id)
            if cursor_doc.exists:
                query = query.start_after(cursor_doc)

        docs = await asyncio.to_thread(_fetch_docs_sync, query, limit)
        all_items = [serialize_doc(doc) for doc in docs]
        return {"items": all_items}
    except Exception as e:
        error_msg = str(e).lower()
        if "index" in error_msg or "precondition" in error_msg:
            return {"items": []}
        raise e


@router.post("/feed/evaluate/{doc_id}")
@handle_exceptions
async def evaluate_user_item(doc_id: str, request: Request, db=Depends(get_db)):
    try:
        data = await request.json()
        odai = html.escape(str(data.get("odai", "") or "").strip())
        toku = html.escape(str(data.get("toku", "") or "").strip())
        kokoro = html.escape(str(data.get("kokoro", "") or "").strip())
        if len(odai) < 1 or len(toku) < 1 or len(kokoro) < 1:
            raise HTTPException(status_code=400, detail="入力が短すぎます")

        update_data = {
            "human_evaluations": firestore.ArrayUnion(
                [
                    {
                        "user_score": data.get("s_total", 0),
                        "timestamp": firestore.SERVER_TIMESTAMP,
                        "user_slug": data.get("user_slug", "anonymous"),
                    }
                ]
            ),
            "human_comments": firestore.ArrayUnion(
                [
                    {
                        "comment": data.get("human_comment", ""),
                        "timestamp": firestore.SERVER_TIMESTAMP,
                        "user_slug": data.get("user_slug", "anonymous"),
                    }
                ]
            ),
            "is_user_edited": True,
            "feed_ready": False,
        }
        await asyncio.to_thread(
            db.collection("nazokake_items").document(doc_id).update, update_data
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

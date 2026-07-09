import html
import random
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore
from api.deps import get_db, verify_user_token
from models.schemas import BoardPostRequest

router = APIRouter()


@router.get("/items")
async def get_board_items(
    category: str = "nazokake", limit: int = 50, db: firestore.Client = Depends(get_db)
):
    """掲示板の親スレッド＋返信を取得（本番用・スケーラブル設計）。
    親スレッドは複合インデックスを活用してDB側でlimitをかけ、
    返信は絞り込まれた親IDを元に取得しPython側で結合・ソートする。"""
    try:
        col = db.collection("board_posts")

        # 1) 親スレッドの取得（複合インデックスを活用し、データベース側で limit をかける）
        query = (
            col.where(filter=firestore.FieldFilter("parent_id", "==", None))
            .where(filter=firestore.FieldFilter("category", "==", category))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )

        parents = []
        for doc in query.stream():
            d = doc.to_dict() or {}
            d["id"] = doc.id
            d.setdefault("category", "nazokake")
            parents.append(d)

        items = []
        if parents:
            parent_ids = [p["id"] for p in parents]

            # 2) 返信の取得 (IN句で取得。親が絞られているためPython側での処理も超高速)
            replies_by_parent = {}
            for i in range(0, len(parent_ids), 30):
                chunk = parent_ids[i : i + 30]
                for r in col.where(
                    filter=firestore.FieldFilter("parent_id", "in", chunk)
                ).stream():
                    rd = r.to_dict() or {}
                    rd["id"] = r.id
                    rd.setdefault("category", "nazokake")
                    replies_by_parent.setdefault(rd.get("parent_id"), []).append(rd)

            # 型安全なソートキー
            def ts(x):
                v = x.get("created_at")
                return v.timestamp() if hasattr(v, "timestamp") else 0.0

            # 3) 親（新しい順）→ その返信（古い順）で結合
            for p in parents:
                items.append(p)
                kids = replies_by_parent.get(p["id"], [])
                kids.sort(key=ts)
                items.extend(kids)

        return {"items": items}
    except Exception as e:
        print(f"🔥 Board API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/post")
async def create_board_post(
    req: BoardPostRequest,
    user_token: dict = Depends(verify_user_token),
    db: firestore.Client = Depends(get_db),
):
    """投稿/返信の書き込み（トランザクションで1日3回制限を強制）"""
    uid = user_token.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="UIDが見つかりません。")

    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    quota_ref = db.collection("board_quotas").document(uid)
    post_ref = db.collection("board_posts").document()

    @firestore.transactional
    def enforce_quota_and_write(transaction):
        quota_snapshot = quota_ref.get(transaction=transaction)

        if quota_snapshot.exists:
            quota_data = quota_snapshot.to_dict()
            if quota_data.get("date") == today_str:
                if quota_data.get("count", 0) >= 3:
                    raise HTTPException(
                        status_code=429, detail="本日の投稿上限(3回)に達しました。"
                    )
                new_count = quota_data.get("count", 0) + 1
            else:
                new_count = 1
        else:
            new_count = 1

        transaction.set(quota_ref, {"date": today_str, "count": new_count})

        post_data = {
            "body": html.escape(req.body),
            "parent_id": req.parent_id,
            "category": req.category,
            "author_uid": uid,
            "created_at": firestore.SERVER_TIMESTAMP,
            "rand": random.random(),
            "hot_score": 0,
            "reply_count": 0,
        }
        transaction.set(post_ref, post_data)

        if req.parent_id:
            parent_ref = db.collection("board_posts").document(req.parent_id)
            transaction.update(
                parent_ref,
                {
                    "reply_count": firestore.Increment(1),
                    "hot_score": firestore.Increment(10),
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
            )

        return post_data

    try:
        enforce_quota_and_write(db.transaction())
        return {"status": "success", "post_id": post_ref.id}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"書き込みエラー: {str(e)}")

"""共有依存・ユーティリティ（DDD再編の足場）。

各機能ルーター(api/routers/*.py)が import して利用する共通要素を集約する。
- get_db            : Firestore クライアントを返す依存（import時生成を避け DI 化）
- serialize_doc     : ドキュメント→dict 変換（datetime ガード付きの統一版）
- handle_exceptions : sync/async 両対応の例外ハンドラデコレータ
- verify_admin_token: Firebase Auth による管理者トークン検証 + admin_users承認チェックの依存
- security          : HTTPBearer スキーム

※本ファイルは足場として新設。エンドポイントの移植は後続フェーズで行う。
"""

import os
import sys
import inspect
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth, firestore

# 管理者APIで用いる Bearer 認証スキーム
security = HTTPBearer()

ADMIN_USERS_COLLECTION = "admin_users"


def get_db():
    """Firestore クライアントを返す依存。ルーターでは Depends(get_db) で受け取る。"""
    return firestore.client()


def serialize_doc(doc) -> dict:
    """Firestore ドキュメントを dict 化し、doc_id/id を付与する統一版。

    timestamp は datetime のときのみ文字列化する（型ガード付き＝安全側）。
    """
    data = doc.to_dict()
    data["doc_id"] = doc.id
    data["id"] = doc.id
    if "timestamp" in data and isinstance(data["timestamp"], datetime):
        data["timestamp"] = str(data["timestamp"])
    return data


_GENERIC_ERROR_MESSAGE = "Internal Server Error: An unexpected error occurred."


def handle_exceptions(func: Callable) -> Callable:
    """例外を一元処理するデコレータ。HTTPException はそのまま再送出する。

    - async 関数: 例外時に {"status": "error", "message": ...} を返す。
    - sync 関数 : 例外時に HTTP 500 を送出する。

    【ディープ監査#4】以前はf"Internal Server Error: {str(e)}"として生の例外
    メッセージ(接続情報・内部パス等を含み得る)をそのままクライアントへ
    返していた。test_fail_closed.pyが検証している「バックグラウンドタスク側の
    fail closed」と同じ原則を、この同期区間の汎用例外ハンドラにも適用し、
    実際の例外はサーバーログにのみ記録し、レスポンスには固定の汎用文言だけを返す。
    """
    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                print(f"🚨 [Internal Error] {func.__name__}: {e}", file=sys.stderr, flush=True)
                return {
                    "status": "error",
                    "message": _GENERIC_ERROR_MESSAGE,
                }

        return async_wrapper
    else:

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                print(f"🚨 [Internal Error] {func.__name__}: {e}", file=sys.stderr, flush=True)
                raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MESSAGE)

        return sync_wrapper


def _owner_email() -> str:
    """メイン管理者(オーナー)のメールアドレス。環境変数 OWNER_EMAIL で設定する。

    Firestore(admin_users)へ誰も承認済みレコードを持たない初回起動時、この
    メールアドレスと一致するGoogleアカウントだけは「招待を経ずに」自動承認する
    (卵が先か鶏が先か問題のブートストラップ。以降の招待発行はこのオーナーが行う)。
    """
    return os.environ.get("OWNER_EMAIL", "").strip().lower()


def verify_admin_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Firebase Auth の ID トークンを検証し、さらに admin_users コレクションで
    status=="approved" であることを要求する依存(Phase 0: 完全招待制の承認ゲート)。

    【検証の流れ】
    1. Firebase IDトークンの検証(失敗時 401、既存の挙動を維持)。
    2. admin_users/{uid} を参照する。
       - ドキュメントが存在せず、かつトークンのメールアドレスが OWNER_EMAIL と
         一致する場合のみ、その場で status="approved" の管理者レコードを
         ブートストラップ作成する(初回起動時、誰も管理者がいない状態を解消する
         唯一の抜け道。招待を経ていない一般ユーザーはここを通過できない)。
       - ドキュメントが存在しない、かつオーナーでもない場合は 403
         (「招待されていない」ことを示す。旧実装は自己登録すら許していなかった
         ため無反応だったが、要件で明示された「直接アクセスした相手は弾く」を
         明確なエラーメッセージとして返す)。
       - ドキュメントは存在するが status!="approved" の場合は 403
         (承認待ち/却下済み)。
    3. 上記いずれも通過すれば decoded_token を返す(既存の呼び出し元との互換性を
       維持するため、admin_users のデータではなくFirebaseの decoded_token を
       そのまま返す点は変更しない)。
    """
    token = credentials.credentials
    try:
        decoded_token = auth.verify_id_token(token)
    except Exception as e:
        print(f"🚨 トークン検証エラー: {e}", file=sys.stderr, flush=True)
        raise HTTPException(status_code=401, detail=f"Invalid Token: {str(e)}")

    uid = decoded_token.get("uid")
    email = (decoded_token.get("email") or "").strip().lower()

    db = firestore.client()
    doc_ref = db.collection(ADMIN_USERS_COLLECTION).document(uid)
    snapshot = doc_ref.get()

    if not snapshot.exists:
        owner_email = _owner_email()
        if owner_email and email == owner_email:
            now = datetime.now(timezone.utc).isoformat()
            doc_ref.set(
                {
                    "uid": uid,
                    "email": email,
                    "status": "approved",
                    "invited_by": None,
                    "requested_at": now,
                    "approved_by": "bootstrap",
                    "approved_at": now,
                }
            )
            return decoded_token
        raise HTTPException(
            status_code=403,
            detail="このアカウントは招待されていません。管理者からの招待URLを使ってアクセスしてください。",
        )

    data = snapshot.to_dict() or {}
    if data.get("status") != "approved":
        raise HTTPException(
            status_code=403,
            detail="管理者としての承認がまだ完了していません。メイン管理者の承認をお待ちください。",
        )

    return decoded_token


def verify_user_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """一般ユーザー（匿名認証）のIDトークンを検証してUIDを返す"""
    try:
        decoded_token = auth.verify_id_token(credentials.credentials)
        return decoded_token
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"ユーザー認証に失敗しました: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

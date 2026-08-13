"""
api/deps.py
=============
共有依存(apps/evaluator/backend/api/deps.pyと同じ役割・同じ配置)。
各ルーター(api/routers/*.py)がimportして使う共通のDI要素をここに集約する。
"""
from __future__ import annotations

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth, firestore


def get_db():
    """Firestore クライアントを返す依存。ルーターでは Depends(get_db) で受け取る。"""
    return firestore.client()


# 【persona_feature_plan_v3.md Phase6 §6】Firebase匿名認証の適用範囲を
# 掲示板投稿のみ(apps/evaluator/backend)からペルソナ関連API全般へ拡張する。
# apps/evaluator/backend/api/deps.py::verify_user_token と全く同じパターン
# (Security(HTTPBearer())でAuthorizationヘッダーからBearerトークンを取得し、
# firebase_admin.auth.verify_id_token()にそのまま渡す)。
security = HTTPBearer()


def verify_user_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    """一般ユーザー(匿名認証含む)のIDトークンを検証し、デコード済みトークンを返す。

    戻り値のdict(FirebaseのDecodedIdToken)から呼び出し元が`uid`を取り出し、
    narrator_personasのowner_uidとして使う(§6: 所有者判定は必ずFirebase UID、
    user_slug等のサーバー未検証の値は使わない)。
    """
    try:
        return auth.verify_id_token(credentials.credentials)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"ユーザー認証に失敗しました: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

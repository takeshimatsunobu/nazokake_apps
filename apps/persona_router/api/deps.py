"""
api/deps.py
=============
共有依存(apps/evaluator/backend/api/deps.pyと同じ役割・同じ配置)。
各ルーター(api/routers/*.py)がimportして使う共通のDI要素をここに集約する。
"""
from __future__ import annotations

from firebase_admin import firestore


def get_db():
    """Firestore クライアントを返す依存。ルーターでは Depends(get_db) で受け取る。"""
    return firestore.client()

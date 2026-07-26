"""
nazokake_core/firestore_sync.py
==================================
ローカルSQLite(Local SSoT)からFirestoreへの一方向バックアップ同期。

sync_status=="pending"/"error" の行を取り、firebase_adminでFirestoreの対象コレクションへ
Push(冪等/Upsert)する。冪等性と順序逆転防止のため、Firestore上の既存ドキュメントの
updated_at を確認し、ローカルの updated_at が同じかそれより新しい場合のみ上書きする
(Firestoreトランザクション内で判定と書き込みをアトミックに行う)。

失敗時はローカルのsync_statusを"error"にし、次回実行時にリトライ対象として
再度拾い上げる(デッドレター的リトライキュー)。Firestoreはあくまで「読み取り専用
レプリカ/バックアップ」であり、このモジュールはローカルDB→Firestoreの一方向のみを
実行する(クラウド側からの逆方向の書き込みは行わない)。
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

import firebase_admin
from firebase_admin import firestore

from .database import get_pending_sync_batch, mark_sync_failed, mark_synced

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "nazokake_items"

# ローカルDB専用のブックキーピングカラムはFirestore側へは送らない。
_LOCAL_ONLY_FIELDS = {"sync_status", "last_sync_error"}


def _resolve_collection() -> str:
    """環境変数 FIRESTORE_SYNC_COLLECTION で同期先コレクションを上書きできる
    (本番の nazokake_items を汚さずにテスト用コレクションへ向けるため)。"""
    return os.environ.get("FIRESTORE_SYNC_COLLECTION", DEFAULT_COLLECTION)


def _ensure_firebase_app() -> None:
    if not firebase_admin._apps:
        project_id = os.environ.get("GCP_PROJECT_ID") or None
        if project_id:
            firebase_admin.initialize_app(options={"projectId": project_id})
        else:
            firebase_admin.initialize_app()


def _build_push_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in _LOCAL_ONLY_FIELDS and v is not None}


def _push_one_sync(db, collection: str, row: dict[str, Any]) -> str:
    """1件をFirestoreへ冪等/順序保護付きでPushする(同期関数、asyncio.to_threadから呼ぶ)。

    Firestore上の既存ドキュメントのupdated_atがローカルのそれより新しい場合は
    「順序逆転」とみなし、上書きせずスキップする。戻り値は "pushed" または
    "skipped_stale"。
    """
    doc_ref = db.collection(collection).document(row["doc_id"])
    payload = _build_push_payload(row)
    local_updated_at = row.get("updated_at")

    @firestore.transactional
    def _txn(transaction) -> str:
        snapshot = doc_ref.get(transaction=transaction)
        if snapshot.exists:
            remote_updated_at = snapshot.get("updated_at")
            if (
                remote_updated_at is not None
                and local_updated_at is not None
                and remote_updated_at > local_updated_at
            ):
                return "skipped_stale"
        transaction.set(doc_ref, payload)
        return "pushed"

    return _txn(db.transaction())


async def sync_once(batch_size: int = 20) -> dict[str, int]:
    """未同期(pending/error)バッチを1回分処理する。戻り値は件数の集計。"""
    _ensure_firebase_app()
    db = firestore.client()
    collection = _resolve_collection()

    rows = await get_pending_sync_batch(limit=batch_size)
    stats = {"pushed": 0, "skipped_stale": 0, "failed": 0, "total": len(rows)}

    for row in rows:
        doc_id = row["doc_id"]
        try:
            outcome = await asyncio.to_thread(_push_one_sync, db, collection, row)
            await mark_synced(doc_id, row.get("updated_at"))
            stats[outcome] += 1
        except Exception as e:
            sys.stderr.write(
                f"[firestore_sync][DEAD-LETTER] doc_id={doc_id} の同期に失敗しました: {e}\n"
            )
            await mark_sync_failed(doc_id, str(e))
            stats["failed"] += 1

    return stats


async def sync_once_safe(batch_size: int = 20) -> None:
    """instructions/239: apps/evaluator/backend(Cloud Run)がFastAPIのBackgroundTasks
    経由で呼ぶための安全側ラッパー。BackgroundTasksはHTTPレスポンス送出後に実行される
    ため、ここで例外を外へ伝播させてもユーザーには届かずサーバー側のノイズにしか
    ならない。個々のアイテムの同期失敗はsync_once内部で既にmark_sync_failedにより
    次回リトライ対象として記録されるため、ここで捕捉するのは
    get_pending_sync_batch自体の失敗やFirebase初期化失敗等、sync_onceのループに
    到達する前の例外のみを想定している。
    """
    try:
        await sync_once(batch_size=batch_size)
    except Exception as e:  # noqa: BLE001 - BackgroundTasksの外へ例外を漏らさない意図的な捕捉
        logger.warning(f"⚠️ Firestoreバックアップ同期(BackgroundTasks)に失敗しました: {e}")

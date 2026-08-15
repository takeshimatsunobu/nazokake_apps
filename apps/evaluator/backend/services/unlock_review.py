"""services/unlock_review.py
==============================
Ⅱレビュー: 直談判(unlock_requests)への「赦す/リセット/却下」アクション(Phase2)。

apps/persona_main_function が所有するFirestoreコレクション(unlock_requests・
user_penalties)を、同一Firestoreプロジェクトを共有するevaluator/backend側から
直接操作する(cross-serviceのHTTP呼び出しは行わない。管理コクピットが他の
Firestoreネイティブなコレクション(admin_users等)を直接読み書きしているのと
同じ「共有Firestoreへの直接アクセス」パターン)。

【なぜ apps/persona_main_function/services/penalty.py と同名にしなかったか】
このファイルは別サービス(evaluator/backend)に属し、役割は近いが実装は別の
penalty.pyというモジュールが既にpersona_main_function側に存在する。import時の混同を
避けるため、このファイルは処理対象(直談判レビュー)に即した名前にした。

【「赦す」と「リセット」の違い】
  pardon(赦す) : blocked_untilのみクリアする。route_b_countは維持する
                 (次にまた5の倍数へ到達すれば、その時点の段階(1週間/1ヶ月等)で
                 再びブロックされる)。
  reset(リセット): blocked_untilとroute_b_countの両方をクリアする
                 (段階を最初からやり直す完全な白紙化)。
いずれも unlock_requests.status を "resolved" へ、reject は "rejected" へ更新し、
既存の監査証跡(nazokake_core.database.async_append_audit_log)へ記録する。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from nazokake_core.database import async_append_audit_log

PENALTIES_COLLECTION = "user_penalties"
UNLOCK_REQUESTS_COLLECTION = "unlock_requests"


async def pardon(db, client_uuid: str, request_id: str, admin_uid: str) -> None:
    """一時ブロックのみ解除する(ペナルティ回数=route_b_countは維持)。"""
    now = datetime.now(timezone.utc).isoformat()

    await asyncio.to_thread(
        db.collection(PENALTIES_COLLECTION).document(client_uuid).set,
        {"blocked_until": None, "updated_at": now},
        merge=True,
    )
    await asyncio.to_thread(
        db.collection(UNLOCK_REQUESTS_COLLECTION).document(request_id).update,
        {
            "status": "resolved",
            "resolved_action": "pardon",
            "resolved_by": admin_uid,
            "resolved_at": now,
        },
    )
    await async_append_audit_log(
        target_item_id=client_uuid,
        actor=f"admin:{admin_uid}",
        action="UNLOCK_PARDON",
        reason_dict={"request_id": request_id},
    )


async def reset(db, client_uuid: str, request_id: str, admin_uid: str) -> None:
    """ブロックとペナルティ回数(route_b_count)の両方を完全に白紙化する。"""
    now = datetime.now(timezone.utc).isoformat()

    await asyncio.to_thread(
        db.collection(PENALTIES_COLLECTION).document(client_uuid).set,
        {"blocked_until": None, "route_b_count": 0, "updated_at": now},
        merge=True,
    )
    await asyncio.to_thread(
        db.collection(UNLOCK_REQUESTS_COLLECTION).document(request_id).update,
        {
            "status": "resolved",
            "resolved_action": "reset",
            "resolved_by": admin_uid,
            "resolved_at": now,
        },
    )
    await async_append_audit_log(
        target_item_id=client_uuid,
        actor=f"admin:{admin_uid}",
        action="UNLOCK_RESET",
        reason_dict={"request_id": request_id},
    )


async def reject(db, request_id: str, admin_uid: str) -> None:
    """直談判を却下する。user_penalties側には一切触れない(ペナルティは維持)。"""
    now = datetime.now(timezone.utc).isoformat()

    await asyncio.to_thread(
        db.collection(UNLOCK_REQUESTS_COLLECTION).document(request_id).update,
        {"status": "rejected", "resolved_by": admin_uid, "resolved_at": now},
    )
    await async_append_audit_log(
        target_item_id=request_id,
        actor=f"admin:{admin_uid}",
        action="UNLOCK_REJECT",
        reason_dict={},
    )

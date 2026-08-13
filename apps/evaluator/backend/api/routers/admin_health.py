"""api/routers/admin_health.py
===============================
Ⅰ 現状のシステム/インフラ稼働チェック(Phase 1)。

- GET  /dlq          : DLQ(sync_status=="fatal")一覧(admin.pyから移設。ロジック無改変)。
- POST /dlq/action   : DLQへの再試行/破棄(admin.pyから移設。ロジック無改変)。
- GET  /action-required-summary : 「管理者がアクションを起こす必要があるタスク」の
  件数お知らせ(直談判・DLQ・承認待ちデータ・承認待ち管理者)。前回ログイン以降の
  新着件数も同時に返す。
- GET  /api-error-rate : SystemCostLog.success を集計したAPIエラー率。

【なぜunlock_requests/admin_usersはFirestore count()、DLQ/承認待ちデータはSQLite
COUNT なのか】このアプリはLocal-First(ローカルSQLiteが正、Firestoreは一方向
バックアップ)アーキテクチャを採用しており、DLQ(sync_status)・承認待ちデータ
(gemini_status/elyza_status)はSQLite側のカラムでしか判定できない(sync_status
はそもそも「Firestoreへ同期できたか」を表す値であり、Firestore側には存在
しない/信頼できない)。一方 unlock_requests(apps/persona_router管理)・
admin_users は元からFirestoreネイティブなコレクションなので、要件で指定された
通りFirestoreのcount()集約クエリ(ドキュメント本体を取得しない軽量なもの)を使う。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Union

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore
from google.api_core.exceptions import FailedPrecondition
from google.cloud.firestore_v1.base_query import FieldFilter
from sqlalchemy import func, select

from api.deps import get_db, handle_exceptions, verify_admin_token
from models.schemas import (
    ActionRequiredCategory,
    ActionRequiredSummaryResponse,
    ApiErrorRateByService,
    ApiErrorRateResponse,
    DatasetLayerCount,
    DatasetLayerSummaryResponse,
    DlqActionRequest,
    DlqActionResponse,
    DlqListResponse,
    ErrorEnvelope,
)
from nazokake_core.correction_pairs import get_correction_pairs
from nazokake_core.database import (
    NazokakeItemORM,
    async_count_dlq_items,
    async_count_dlq_items_since,
    async_count_pending_items,
    async_count_pending_items_since,
    async_discard_dlq_item,
    async_get_dlq_items,
    async_retry_dlq_item,
    get_session,
)
from nazokake_core.persona_reactions import count_reactions
from nazokake_core.schemas import SystemCostLog

# persona_feature_plan_v3.md §5.2: tools/extract_training_data.pyのQUALITY_SCORE_MINと
# 揃える(第1層(構造)の件数サマリが実際の抽出条件と食い違わないようにするため)。
STRUCTURE_LAYER_QUALITY_SCORE_MIN = 4.0

router = APIRouter()

ADMIN_USERS_COLLECTION = "admin_users"
UNLOCK_REQUESTS_COLLECTION = "unlock_requests"
SYSTEM_COSTS_COLLECTION = "system_costs"

# last_login_atの更新頻度をこの間隔でデバウンスする(要件通り1時間)。
LAST_LOGIN_DEBOUNCE = timedelta(hours=1)

# APIエラー率の集計対象(admin_costs.pyの_fetch_recent_costsと同じ規模感)。
ERROR_RATE_SAMPLE_LIMIT = 200


# ------------------------------------------------------------
# DLQ(admin.pyから移設。中身は無改変)
# ------------------------------------------------------------
@router.get("/dlq", response_model=Union[DlqListResponse, ErrorEnvelope])
@handle_exceptions
async def get_dlq_items(admin_token: dict = Depends(verify_admin_token)):
    """DLQ(sync_status=="fatal"、ポイズンピル隔離済み)の一覧を取得する。

    last_sync_error(隔離理由)とretry_countを含めて返す。
    """
    items = await async_get_dlq_items()
    return {"items": items}


@router.post("/dlq/action", response_model=Union[DlqActionResponse, ErrorEnvelope])
@handle_exceptions
async def apply_dlq_action(
    req: DlqActionRequest,
    admin_token: dict = Depends(verify_admin_token),
):
    """DLQに隔離されたアイテムへ「再試行」または「破棄」を適用する。

    対象が存在しない、または既にfatal(隔離中)でない場合は404。操作が成功した場合、
    直後に既存データを一切破壊しない追記専用の監査証跡(Audit Trail)を記録する。
    """
    reason_dict = {"requested_action": req.action}
    if req.action == "retry":
        found = await async_retry_dlq_item(
            req.doc_id, actor="admin", reason_dict=reason_dict
        )
    else:
        found = await async_discard_dlq_item(
            req.doc_id, actor="admin", reason_dict=reason_dict
        )

    if not found:
        raise HTTPException(status_code=404, detail="対象のDLQアイテムが見つかりません")

    return {"status": "success", "doc_id": req.doc_id, "action": req.action}


# ------------------------------------------------------------
# お知らせバッジ: action-required-summary
# ------------------------------------------------------------
def _count_firestore_sync(query, label: str) -> tuple[int, str | None]:
    """Firestoreのcount()集約クエリを実行し、件数のみ返す(ドキュメント本体は
    一切取得しない)。同期APIのためasyncio.to_threadで呼ぶこと。

    【防御的実装】等価フィルタ+range/orderByの組み合わせは複合インデックスを
    要求し、未作成だとgoogle.api_core.exceptions.FailedPrecondition(HTTP 400)が
    飛んでくる。これをそのまま伝播させるとResponseValidationErrorに化けて
    ブラウザにCORSエラーとして見える障害を引き起こす(実際に発生した障害、
    api/routers/admin_review.py::_fetch_pending_unlock_requests_syncの
    docstring参照)ため、ここで確実に捕捉し(件数, 警告メッセージ)へ変換する。
    """
    try:
        result = query.count().get()
        return result[0][0].value, None
    except FailedPrecondition as e:
        warning = f"{label}: Firestoreの複合インデックスが未作成のため件数を0として扱いました。詳細: {e}"
        print(f"⚠️ [action-required-summary] {warning}")
        return 0, warning
    except Exception as e:
        warning = f"{label}: 件数取得中に予期しないエラーが発生しました: {e}"
        print(f"⚠️ [action-required-summary] {warning}")
        return 0, warning


async def _count_firestore(db, collection: str, field: str, value) -> tuple[int, str | None]:
    query = db.collection(collection).where(filter=FieldFilter(field, "==", value))
    return await asyncio.to_thread(_count_firestore_sync, query, f"{collection}.{field}=={value}")


async def _zero() -> tuple[int, str | None]:
    """asyncio.gather へ _count_firestore_since と型を揃えて渡すためのプレースホルダ。"""
    return 0, None


async def _zero_int() -> int:
    """asyncio.gather へ async_count_dlq_items_since 等(SQLite側、plain int)と
    型を揃えて渡すためのプレースホルダ。previous_login_atが無い(初回ログイン)時に使う。
    """
    return 0


async def _count_firestore_since(
    db, collection: str, field: str, value, since_field: str, since_value: str | None
) -> tuple[int, str | None]:
    # previous_login_at が無い(初回ログイン)場合、比較対象となる基準時刻が
    # 存在しないため「新着」は算出できない。0を返す(誤って全件を「新着」扱い
    # して初回ログイン時に巨大な数字を出さないための安全策)。
    if not since_value:
        return 0, None
    query = (
        db.collection(collection)
        .where(filter=FieldFilter(field, "==", value))
        .where(filter=FieldFilter(since_field, ">", since_value))
    )
    return await asyncio.to_thread(
        _count_firestore_sync, query, f"{collection}.{field}=={value} AND {since_field}>..."
    )


def _touch_last_login_sync(db, uid: str, now: datetime) -> str | None:
    """admin_users/{uid}.last_login_at を読み出し、必要であれば(デバウンス済み)
    現在時刻へ更新する。戻り値は「今回の集計で基準にする値」= 更新前の値
    (previous_login_at)。同期APIのためasyncio.to_threadで呼ぶこと。
    """
    doc_ref = db.collection(ADMIN_USERS_COLLECTION).document(uid)
    snapshot = doc_ref.get()
    data = snapshot.to_dict() if snapshot.exists else {}
    previous_login_at = (data or {}).get("last_login_at")

    should_update = True
    if previous_login_at:
        try:
            prev_dt = datetime.fromisoformat(previous_login_at)
            should_update = (now - prev_dt) > LAST_LOGIN_DEBOUNCE
        except ValueError:
            should_update = True

    if should_update:
        doc_ref.set({"last_login_at": now.isoformat()}, merge=True)

    return previous_login_at


@router.get("/action-required-summary", response_model=ActionRequiredSummaryResponse)
@handle_exceptions
async def get_action_required_summary(
    admin_token: dict = Depends(verify_admin_token), db=Depends(get_db)
):
    uid = admin_token.get("uid")
    now = datetime.now(timezone.utc)

    # 【順序が重要】previous_login_atは「更新前」の値を使う(今回のログイン自体を
    # 新着判定に含めてしまわないため)。_touch_last_login_syncは読み出しと
    # (デバウンス済みの)更新を1回のFirestore往復で済ませる。
    previous_login_at = await asyncio.to_thread(_touch_last_login_sync, db, uid, now)

    (
        (unlock_total, unlock_warn),
        (unlock_new, unlock_new_warn),
        dlq_total,
        dlq_new,
        review_total,
        review_new,
        (admin_total, admin_warn),
        (admin_new, admin_new_warn),
    ) = await asyncio.gather(
        _count_firestore(db, UNLOCK_REQUESTS_COLLECTION, "status", "pending"),
        _count_firestore_since(
            db, UNLOCK_REQUESTS_COLLECTION, "status", "pending", "created_at", previous_login_at
        ),
        async_count_dlq_items(),
        async_count_dlq_items_since(previous_login_at) if previous_login_at else _zero_int(),
        async_count_pending_items(),
        async_count_pending_items_since(previous_login_at) if previous_login_at else _zero_int(),
        _count_firestore(db, ADMIN_USERS_COLLECTION, "status", "pending_approval"),
        _count_firestore_since(
            db, ADMIN_USERS_COLLECTION, "status", "pending_approval", "requested_at", previous_login_at
        ),
    )

    # DLQ/承認待ちデータ(SQLite側)はそもそもFirestoreの複合インデックス問題と
    # 無縁のため警告を持たない。Firestore側4件のうち発生したものだけを連結する。
    warnings = [w for w in (unlock_warn, unlock_new_warn, admin_warn, admin_new_warn) if w]

    total = unlock_total + dlq_total + review_total + admin_total

    return ActionRequiredSummaryResponse(
        total=total,
        unlock=ActionRequiredCategory(total=unlock_total, new=unlock_new),
        dlq=ActionRequiredCategory(total=dlq_total, new=dlq_new),
        review=ActionRequiredCategory(total=review_total, new=review_new),
        admin_approval=ActionRequiredCategory(total=admin_total, new=admin_new),
        previous_login_at=previous_login_at,
        warning="; ".join(warnings) if warnings else None,
    )


# ------------------------------------------------------------
# APIエラー率
# ------------------------------------------------------------
def _fetch_recent_system_costs_sync(db, limit: int) -> list[SystemCostLog]:
    query = db.collection(SYSTEM_COSTS_COLLECTION).order_by(
        "timestamp", direction=firestore.Query.DESCENDING
    )
    try:
        docs = list(query.limit(limit).stream())
        return [SystemCostLog(**d.to_dict()) for d in docs]
    except Exception as e:
        # 単一フィールドのorder_byのみ(複合インデックス不要)のため通常起きないが、
        # 万一の障害でもAPIエラー率タイルだけが「0件」表示に縮退し、他のパネルの
        # 描画を巻き込まないようにする。
        print(f"⚠️ [api-error-rate] system_costsの取得に失敗しました: {e}")
        return []


@router.get("/api-error-rate", response_model=ApiErrorRateResponse)
@handle_exceptions
async def get_api_error_rate(
    admin_token: dict = Depends(verify_admin_token), db=Depends(get_db)
):
    """直近ERROR_RATE_SAMPLE_LIMIT件のsystem_costsから、全体および
    service_type別のエラー率(success=falseの割合)を算出する。

    Cloud Logging/Cloud Monitoringは一切使わない(既存のsystem_costs自己ログ
    基盤を再利用するだけで、追加のIAM権限やAPIクライアントを必要としない)。
    """
    costs = await asyncio.to_thread(
        _fetch_recent_system_costs_sync, db, ERROR_RATE_SAMPLE_LIMIT
    )

    total = len(costs)
    failed = sum(1 for c in costs if not c.success)
    error_rate = (failed / total) if total else 0.0

    by_service_counts: dict[str, dict[str, int]] = {}
    for c in costs:
        bucket = by_service_counts.setdefault(c.service_type, {"total": 0, "failed": 0})
        bucket["total"] += 1
        if not c.success:
            bucket["failed"] += 1

    by_service = [
        ApiErrorRateByService(
            service_type=service_type,
            total=counts["total"],
            failed=counts["failed"],
            error_rate=(counts["failed"] / counts["total"]) if counts["total"] else 0.0,
        )
        for service_type, counts in sorted(by_service_counts.items())
    ]

    return ApiErrorRateResponse(
        total=total,
        failed=failed,
        error_rate=round(error_rate, 4),
        sample_size=total,
        by_service=by_service,
    )


# ------------------------------------------------------------
# persona_feature_plan_v3.md Phase8 §6: 3層(構造/反応/訂正)データセット集計
# ------------------------------------------------------------
async def _count_structure_layer() -> int:
    """第1層(構造)の件数 = tools/extract_training_data.pyと同じ抽出条件
    (s_total >= STRUCTURE_LAYER_QUALITY_SCORE_MIN かつ toku/kokoroが揃っている)を
    満たすnazokake_items行数。json_extractでresult列のtoku/kokoroキーの有無を
    直接SQLiteに判定させ、行本体は一切取得しない。
    """
    async with get_session() as session:
        stmt = select(func.count()).select_from(NazokakeItemORM).where(
            NazokakeItemORM.s_total.is_not(None),
            NazokakeItemORM.s_total >= STRUCTURE_LAYER_QUALITY_SCORE_MIN,
            NazokakeItemORM.odai.is_not(None),
            func.json_extract(NazokakeItemORM.result, "$.toku").is_not(None),
            func.json_extract(NazokakeItemORM.result, "$.kokoro").is_not(None),
        )
        result = await session.execute(stmt)
        return result.scalar_one()


@router.get("/dataset-layer-summary", response_model=DatasetLayerSummaryResponse)
@handle_exceptions
async def get_dataset_layer_summary(
    admin_token: dict = Depends(verify_admin_token), db=Depends(get_db)
):
    """3層(構造/反応/訂正)データセットの件数サマリ(§6)。

    - 構造(第1層): tools/extract_training_data.pyと同じ抽出条件を満たす
      nazokake_items行数(SQLite COUNT、行本体は取得しない)。
    - 反応(第2層): persona_reactionsコレクションの全件数
      (nazokake_core.persona_reactions.count_reactions、集計失敗時は内部で
      0へ縮退するためここでは追加のtry/exceptを要しない)。
    - 訂正(第3層): 赤ペン添削(nazokake_core.correction_pairs.get_correction_pairs、
      SQLite user_akapen系統に一本化済み、Phase9)の件数。現状は全件を実際に
      読み取ってからlen()を取る実装であり、count()集約クエリのような軽量な件数
      取得ではない(現時点では小規模なため許容、規模が拡大した場合は専用の
      count専用パスへの分離を検討すること)。
    """
    warnings = []

    try:
        structure_total = await _count_structure_layer()
    except Exception as e:
        warnings.append(f"構造(第1層)の集計に失敗しました: {e}")
        structure_total = 0

    reaction_total = await asyncio.to_thread(count_reactions, db)

    try:
        correction_total = len(await get_correction_pairs(db))
    except Exception as e:
        warnings.append(f"訂正(第3層)の集計に失敗しました: {e}")
        correction_total = 0

    return DatasetLayerSummaryResponse(
        structure=DatasetLayerCount(label="第1層(構造)", total=structure_total),
        reaction=DatasetLayerCount(label="第2層(反応)", total=reaction_total),
        correction=DatasetLayerCount(label="第3層(訂正)", total=correction_total),
        warning="; ".join(warnings) if warnings else None,
    )

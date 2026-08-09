"""テレメトリ記録ルーター（DDD再編で endpoints.py から切り出し）。

POST /metrics/log : フロントからの計測イベントを telemetry_logs に記録する。
admin_db グローバル参照を廃し、Depends(get_db) で DI する。
"""

import asyncio

from fastapi import APIRouter, Depends
from firebase_admin import firestore

from api.deps import get_db, handle_exceptions, verify_admin_token
from models.schemas import TelemetryLogRequest
from nazokake_core.database import sync_upsert_item

router = APIRouter()

# SSoT §8.2: ハイブリッド境界の例外として直接書き込みが許可された周辺機能ドメイン。
_TELEMETRY_LOGS_COLLECTION = "telemetry_logs"

# 「アプリ利用状況」パネル向け簡易集計のサンプル件数上限。Firestoreは読み取り
# ドキュメント数に応じて課金されるため、全件集計(コレクション全体のstream())は
# 行わず、直近このN件のみをtimestamp降順でfetchしてインメモリで集計する
# (=真の全期間PV/UUではなく「直近N件から見た近似値」)。
_SUMMARY_SAMPLE_LIMIT = 500


@router.post("/metrics/log")
@handle_exceptions
def log_telemetry(req: TelemetryLogRequest, db=Depends(get_db)):
    db.collection(_TELEMETRY_LOGS_COLLECTION).document().set(
        {
            "user_slug": req.user_slug,
            "event_name": req.event_name,
            "duration": req.duration,
            "tab_name": req.tab_name,
            "comment": req.comment,
            "timestamp": firestore.SERVER_TIMESTAMP,
        }
    )

    # 💡 モデレーション（荒らし対策）連動ロジック:
    # 生成画面での評価（gen_eval:*）が行われた場合、該当のなぞかけドキュメント(ローカルDB)に
    # 人間の手が加わった証 (is_user_edited = True) を刻印し、管理コックピットの検問所へ送致する。
    if req.event_name and req.event_name.startswith("gen_eval:") and req.tab_name:
        try:
            sync_upsert_item({"doc_id": req.tab_name, "is_user_edited": True})
        except Exception as e:
            print(f"⚠️ モデレーションフラグ更新エラー (無視して継続): {e}")

    return {"status": "success"}


def _fetch_recent_telemetry_sync(db, limit: int) -> list:
    """Firestoreのstream()を同期的に実行し、リスト化して返すヘルパー関数。"""
    query = db.collection(_TELEMETRY_LOGS_COLLECTION).order_by(
        "timestamp", direction=firestore.Query.DESCENDING
    )
    return list(query.limit(limit).stream())


@router.get("/metrics/summary")
@handle_exceptions
async def get_metrics_summary(
    db=Depends(get_db), admin_token: dict = Depends(verify_admin_token)
):
    """「アプリ利用状況」パネル向けの簡易集計(直近_SUMMARY_SAMPLE_LIMIT件から算出)。

    app.js が記録するevent_nameの規約('page_view'/'page_leave'/その他アクション)を
    前提に、PV('page_view'件数)・UU(user_slugの重複排除件数)・平均滞在時間
    ('page_leave'のduration平均)・イベント別件数を、fetchした1バッチ分から
    インメモリで算出する(複雑な集計クエリはFirestoreの読み取り課金を増やすため
    採用しない)。
    """
    docs = await asyncio.to_thread(
        _fetch_recent_telemetry_sync, db, _SUMMARY_SAMPLE_LIMIT
    )
    rows = [doc.to_dict() or {} for doc in docs]

    pv = sum(1 for r in rows if r.get("event_name") == "page_view")
    uu = len({r["user_slug"] for r in rows if r.get("user_slug")})

    leave_durations = [
        r["duration"]
        for r in rows
        if r.get("event_name") == "page_leave"
        and isinstance(r.get("duration"), (int, float))
    ]
    avg_duration_sec = (
        round(sum(leave_durations) / len(leave_durations), 1)
        if leave_durations
        else 0.0
    )

    event_counts: dict[str, int] = {}
    for r in rows:
        name = r.get("event_name") or "(unknown)"
        event_counts[name] = event_counts.get(name, 0) + 1
    events = [
        {"event_name": name, "count": count}
        for name, count in sorted(
            event_counts.items(), key=lambda kv: kv[1], reverse=True
        )
    ]

    return {
        "pv": pv,
        "uu": uu,
        "avg_duration_sec": avg_duration_sec,
        "events": events,
        "sampled_events": len(rows),
        "note": f"直近{_SUMMARY_SAMPLE_LIMIT}件のイベントログに基づく簡易集計です",
    }

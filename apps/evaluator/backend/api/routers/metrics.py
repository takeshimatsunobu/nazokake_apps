"""テレメトリ記録ルーター（DDD再編で endpoints.py から切り出し）。

POST /metrics/log : フロントからの計測イベントを telemetry_logs に記録する。
admin_db グローバル参照を廃し、Depends(get_db) で DI する。
"""

from fastapi import APIRouter, Depends
from firebase_admin import firestore

from api.deps import get_db, handle_exceptions
from models.schemas import TelemetryLogRequest
from nazokake_core.database import sync_upsert_item

router = APIRouter()


@router.post("/metrics/log")
@handle_exceptions
def log_telemetry(req: TelemetryLogRequest, db=Depends(get_db)):
    db.collection("telemetry_logs").document().set(
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

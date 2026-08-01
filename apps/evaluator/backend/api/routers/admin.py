# ... (既存コード)

import asyncio
from datetime import datetime, timezone
from typing import Union
from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore
from api.deps import verify_admin_token, handle_exceptions
from models.schemas import (
    AdminActionResponse,
    AdminDeployResponse,
    AuditLogListResponse,
    DlqActionRequest,
    DlqActionResponse,
    DlqListResponse,
    ErrorEnvelope,
    HumanActionRequest,
)
from nazokake_core.database import (
    async_discard_dlq_item,
    async_get_audit_logs,
    async_get_dlq_items,
    async_get_item,
    async_retry_dlq_item,
    async_upsert_item,
)
from nazokake_core.firestore_sync import sync_once_safe

router = APIRouter()

# 【instructions/203: RCEリスクの排除】以前はこのエンドポイントがブラウザからの
# HTTPリクエストを起点にsubprocess.Popen(["powershell", ..., deploy_to_vm.ps1])を
# 直接起動していた(instructions/172/187)。これはSRE監査により「任意コード実行
# (RCE)・特権エスケープのリスク」として明確にRejectされた。このファイルは
# 以後、Firestoreの system_configs/deploy_state ドキュメントへ要求を書き込む
# だけに留める。実際のデプロイスクリプト実行(git自動コミット・
# tools/deploy/deploy_to_vm.ps1のsubprocess起動)は、ネットワークから到達不能な
# ローカル常駐のポーリングデーモン tools/deploy_poll_daemon.py へ完全に移設した。
_DEPLOY_STATE_COLLECTION = "system_configs"
_DEPLOY_STATE_DOC = "deploy_state"
# デプロイ要求が既に処理待ち/処理中とみなすstatus値(この状態のときは新規要求を
# 409で拒否する。実際の二重起動防止はtools/deploy_poll_daemon.py側のFirestore
# トランザクションによるアトミックなクレームで保証されるため、ここでの判定は
# あくまでUXのための早期リジェクトに過ぎない)。
_DEPLOY_IN_PROGRESS_STATUSES = {"pending", "running"}

# モデルキー → ステータスフィールド名 / アクション → ステータス値
_MODEL_STATUS_FIELD = {"gemini": "gemini_status", "elyza": "elyza_status"}
_ACTION_TO_STATUS = {
    "golden": "golden",
    "approve": "approved",
    "reject": "rejected",
    "delete": "deleted",
}
# 「未評価でない（＝処理済み）」とみなすステータス集合
_RESOLVED_STATUSES = {"golden", "approved", "rejected", "deleted", "n/a"}


def _resolve_statuses(data: dict) -> tuple:
    """文書から (gemini_status, elyza_status) を決定する（レガシー互換の既定値込み）。

    新フィールド未設定の旧文書は is_golden_data / is_approved から既定値を補う。
    ELYZA 未生成（result_llmjp / nazokake_text_llmjp が無い）は 'n/a'（対象外）。
    """
    legacy_golden = bool(data.get("is_golden_data"))
    legacy_approved = bool(data.get("is_approved"))
    legacy = (
        "golden" if legacy_golden else ("approved" if legacy_approved else "pending")
    )
    g = data.get("result_gemini") or data.get("result") or {}
    has_gemini = bool(g.get("toku") or g.get("kokoro") or data.get("nazokake_text"))
    has_elyza = bool(
        (data.get("result_llmjp") or {}).get("toku")
        or (data.get("result_llmjp") or {}).get("kokoro")
        or data.get("nazokake_text_llmjp")
    )
    # データの無いモデルは 'n/a'（対象外＝処理済み扱い）。これにより単一モデル文書も resolved 判定が成立する。
    default_g = legacy if has_gemini else "n/a"
    default_e = legacy if has_elyza else "n/a"
    return data.get("gemini_status", default_g), data.get("elyza_status", default_e)


@router.post("/action", response_model=Union[AdminActionResponse, ErrorEnvelope])
@handle_exceptions
async def apply_human_action(
    req: HumanActionRequest,
    admin_token: dict = Depends(verify_admin_token),
):
    """管理者キュレーション: 対象なぞかけの gemini_status / elyza_status を更新する。

    Phase 4.11 の DPO抽出(Tier A/B)は、この gemini_status/elyza_status を
    golden/approved/rejected に更新する手段が無いまま(このエンドポイント自体が
    消失していたため)恒久的に0件抽出になっていた欠落を復旧するもの。
    """
    status_field = _MODEL_STATUS_FIELD[req.model]
    new_status = _ACTION_TO_STATUS[req.action]

    existing = await async_get_item(req.target_slug)
    if existing is None:
        raise HTTPException(status_code=404, detail="対象のなぞかけが見つかりません")

    await async_upsert_item({"doc_id": req.target_slug, status_field: new_status})
    # 【instructions/283】Cloud RunはCPUをリクエスト処理中のみ割り当てる仕様のため、
    # レスポンス送出後に実行されるBackgroundTasksはスケジュールされる保証が無く、
    # 同期が発火しないまま次のリクエストまでインスタンスがサスペンドされ得た
    # (instructions/282のFirestore同期欠落調査で判明)。キュレーター操作の
    # 書き込み直後、レスポンスを返す前に同期的に完了させることで、CPUが
    # 確実に割り当てられているリクエスト処理中に同期を完結させる。
    await sync_once_safe()
    updated = await async_get_item(req.target_slug)
    # 【絶対制約】sync_status(クラウド同期状態)はUI向けレスポンスに含めない。
    ui_updated = {k: v for k, v in updated.items() if k not in ("sync_status", "last_sync_error")}
    # APIの処理結果("success")とドキュメント自身の"status"フィールド(なぞかけの
    # 生成ステータス、例:"pending")はキー名が衝突するため、"data"キーの下へ
    # ネストして明確に分離する(旧実装は {"status": "success", **doc} のスプレッドで
    # ドキュメント側のstatusがsuccessを上書きしてしまうバグを内包していた)。
    return {"status": "success", "data": ui_updated}


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
        found = await async_retry_dlq_item(req.doc_id, actor="admin", reason_dict=reason_dict)
    else:
        found = await async_discard_dlq_item(req.doc_id, actor="admin", reason_dict=reason_dict)

    if not found:
        raise HTTPException(status_code=404, detail="対象のDLQアイテムが見つかりません")

    return {"status": "success", "doc_id": req.doc_id, "action": req.action}


@router.get("/audit_logs", response_model=Union[AuditLogListResponse, ErrorEnvelope])
@handle_exceptions
async def get_audit_logs(admin_token: dict = Depends(verify_admin_token)):
    """監査証跡(audit_logs)を作成日時の降順で最大100件取得する。"""
    items = await async_get_audit_logs(limit=100)
    return {"items": items}


@router.post("/deploy", response_model=Union[AdminDeployResponse, ErrorEnvelope])
@handle_exceptions
async def trigger_deploy(admin_token: dict = Depends(verify_admin_token)):
    """検証サーバーへの閉域GitOps(Pull型)デプロイを「要求」する(instructions/203)。

    【アーキテクチャ変更】このエンドポイントはサブプロセスを一切起動しない。
    行うことはFirestoreの system_configs/deploy_state ドキュメントへ
    {"status": "pending", ...} を書き込むことだけであり、実際のデプロイ
    スクリプト(tools/deploy/deploy_to_vm.ps1)の実行は、ローカル常駐の
    tools/deploy_poll_daemon.py がこのドキュメントの変化をポーリング(Pull)で
    検知し、Firestoreトランザクションでアトミックにクレームした上で非同期に
    引き受ける。ブラウザ(未信頼な入力元)からのHTTPリクエストが、ローカル
    マシン上のプロセス起動に直接つながる経路は構造的に存在しない。

    この決定的な変更点により、このエンドポイント自体はWindows PowerShell/
    gcloud CLIの存在にもローカルgitリポジトリの存在にも依存しなくなった
    (Cloud Run上で実行されても問題なく完了する)。
    """
    db = firestore.client()
    doc_ref = db.collection(_DEPLOY_STATE_COLLECTION).document(_DEPLOY_STATE_DOC)

    snapshot = await asyncio.to_thread(doc_ref.get)
    current = (snapshot.to_dict() or {}) if snapshot.exists else {}
    if current.get("status") in _DEPLOY_IN_PROGRESS_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="デプロイが既に進行中です。完了までお待ちください。",
        )

    now = datetime.now(timezone.utc).isoformat()
    requested_by = admin_token.get("uid") if isinstance(admin_token, dict) else None
    await asyncio.to_thread(
        doc_ref.set,
        {
            "deploy_requested": True,
            "status": "pending",
            "requested_at": now,
            "requested_by": requested_by,
            "claimed_at": None,
            "completed_at": None,
            "last_error": None,
        },
    )

    return {
        "status": "success",
        "message": (
            "デプロイ要求をFirestoreへ登録しました。"
            "ローカルのデプロイポーリングデーモンが検知し、非同期で実行します。"
        ),
        "committed_files": [],
        "log_path": "/data/deploy.log",
    }

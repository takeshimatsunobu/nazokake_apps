# ... (既存コード)

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_db, serialize_doc, verify_admin_token, handle_exceptions
from models.schemas import HumanActionRequest

router = APIRouter()

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


@router.post("/action")
@handle_exceptions
async def apply_human_action(
    req: HumanActionRequest,
    db=Depends(get_db),
    admin_token: dict = Depends(verify_admin_token),
):
    """管理者キュレーション: 対象なぞかけの gemini_status / elyza_status を更新する。

    Phase 4.11 の DPO抽出(Tier A/B)は、この gemini_status/elyza_status を
    golden/approved/rejected に更新する手段が無いまま(このエンドポイント自体が
    消失していたため)恒久的に0件抽出になっていた欠落を復旧するもの。
    """
    status_field = _MODEL_STATUS_FIELD[req.model]
    new_status = _ACTION_TO_STATUS[req.action]

    doc_ref = db.collection("nazokake_items").document(req.target_slug)
    doc = await asyncio.to_thread(doc_ref.get)
    if not doc.exists:
        raise HTTPException(status_code=404, detail="対象のなぞかけが見つかりません")

    await asyncio.to_thread(doc_ref.update, {status_field: new_status})
    updated_doc = await asyncio.to_thread(doc_ref.get)
    return {"status": "success", **serialize_doc(updated_doc)}

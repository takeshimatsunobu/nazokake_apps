"""api/routers/corrections.py
==============================
POST /v1/corrections: 「赤ペン」添削の送信(Phase3)。

frontend/app.js の handleRedPenStub() が呼び出す予定の本実装。元のAI生成
(nazokake_results.{original_doc_id})を検証した上で、人間の添削案を保存する。

【DPO用データ形状であることについて】元テキスト(rejected相当)と添削後テキスト
(chosen相当)の両方を1ドキュメントへスナップショットとして保存する。これにより、
将来のDPOペア抽出(apps/evaluator/backend/scripts/extract_dpo_data.py相当の
バッチ)がこのコレクションを直接読むだけで {prompt, chosen, rejected} を
組み立てられる(元ドキュメントとの突き合わせ・JOINが不要)。実際の抽出バッチ
本体は本フェーズのスコープ外(データ形状のみ用意する)。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from api.routers.generate import RESULTS_COLLECTION
from models.schemas import CorrectionCreate, CorrectionResponse

router = APIRouter()

CORRECTIONS_COLLECTION = "corrections"


@router.post("/v1/corrections", response_model=CorrectionResponse)
async def submit_correction(req: CorrectionCreate, db=Depends(get_db)):
    original_ref = db.collection(RESULTS_COLLECTION).document(req.original_doc_id)
    original_snapshot = original_ref.get()
    if not original_snapshot.exists:
        raise HTTPException(
            status_code=404, detail=f"添削対象のdoc_idが見つかりません: {req.original_doc_id}"
        )
    original = original_snapshot.to_dict() or {}

    odai = original.get("odai", "")
    corrected_nazokake_text = (
        f"「{odai}」とかけて、「{req.corrected_toku}」と解く。\nその心は、{req.corrected_kokoro}"
    )

    correction_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    db.collection(CORRECTIONS_COLLECTION).document(correction_id).set(
        {
            "correction_id": correction_id,
            "original_doc_id": req.original_doc_id,
            "client_uuid": req.client_uuid,
            "pen_name": req.pen_name,
            "odai": odai,
            "persona_id": original.get("persona_id"),
            # rejected相当(添削元・元のAI生成のスナップショット)
            "original_toku": original.get("toku", ""),
            "original_kokoro": original.get("kokoro", ""),
            "original_nazokake_text": original.get("nazokake_text", ""),
            # chosen相当(添削後)
            "corrected_toku": req.corrected_toku,
            "corrected_kokoro": req.corrected_kokoro,
            "corrected_nazokake_text": corrected_nazokake_text,
            "created_at": now,
        }
    )

    return CorrectionResponse(
        correction_id=correction_id, original_doc_id=req.original_doc_id, submitted_at=now
    )

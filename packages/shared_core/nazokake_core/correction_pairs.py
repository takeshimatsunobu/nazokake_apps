"""
nazokake_core/correction_pairs.py
====================================
persona_feature_plan_v3.md Phase8 §5.6 / Phase9クリーンアップ: 第3層(訂正)
データセット基盤。

「赤ペン」添削は歴史的に2系統(persona_router版Firestore `corrections`コレクション
＝系統A、evaluator道場破りフィードのSQLite `nazokake_items` origin_type=
"user_akapen"行＝系統B)に分かれていたが、実件数を比較した結果いずれも0件
(未使用)であったため、Phase9クリーンアップで**系統Bへ一本化**した
(persona_router側のPOST /v1/corrections・corrections コレクションへの書き込みは
廃止済み)。本モジュールは単一系統(系統B)のみを読む、Phase8時点の
「2系統統合読み取り」から簡素化したロジックを提供する。§5.1の共通エンベロープ
でラップして返す点は変わらない。

【s_total差分について】系統Bの添削行(SQLite側の新規INSERT行)は挿入時点で
s_totalが一切設定されない(未評価)。訂正前後のs_total差分は、この読み取り関数が
新たな評価をトリガーすることはせず(副作用のある処理を「読み取り」関数に混ぜ
ない)、「元の行(source_item_id参照先)のs_totalと、添削行自身のs_total(将来、
通常の評価パイプラインを経て埋まった場合のみ)の差」として算出する。どちらか
一方でも欠けている場合はNone(差分不明)とする。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from .database import NazokakeItemORM, get_session
from .dataset_envelope import build_envelope
from .narrator_personas import get_persona


def _resolve_owner_uid_and_origin(
    db, persona_id: str | None, cache: dict[str, str | None]
) -> tuple[str | None, str]:
    """persona_idからowner_uidとdata_originを引く。"""
    if not persona_id or persona_id == "No_Data":
        return None, "no_data"
    if persona_id not in cache:
        persona_doc = get_persona(db, persona_id)
        cache[persona_id] = (persona_doc or {}).get("owner_uid")
    owner_uid = cache[persona_id]
    if owner_uid == "SYSTEM":
        return owner_uid, "builtin"
    if owner_uid:
        return owner_uid, "custom"
    return None, "no_data"


async def get_correction_pairs(db) -> list[dict[str, Any]]:
    """赤ペン添削(SQLite `nazokake_items` origin_type="user_akapen"行)を読み、
    共通エンベロープへ変換して返す(§5.6)。narrator_persona_id/version_idと
    訂正前s_totalは、添削行自身ではなく参照元(source_item_id)の行から引く
    (添削行自体はNo_Data/NULLのまま挿入されるため)。
    """
    async with get_session() as session:
        stmt = select(NazokakeItemORM).where(NazokakeItemORM.origin_type == "user_akapen")
        corrected_rows = (await session.execute(stmt)).scalars().all()

        source_ids = {row.source_item_id for row in corrected_rows if row.source_item_id}
        original_rows: dict[str, NazokakeItemORM] = {}
        if source_ids:
            original_stmt = select(NazokakeItemORM).where(NazokakeItemORM.doc_id.in_(source_ids))
            for row in (await session.execute(original_stmt)).scalars().all():
                original_rows[row.doc_id] = row

    owner_uid_cache: dict[str, str | None] = {}
    pairs = []
    for row in corrected_rows:
        original = original_rows.get(row.source_item_id) if row.source_item_id else None

        narrator_persona_id = (
            original.narrator_persona_id
            if original and original.narrator_persona_id and original.narrator_persona_id != "No_Data"
            else (row.narrator_persona_id or "No_Data")
        )
        narrator_persona_version_id = (
            original.narrator_persona_version_id
            if original
            and original.narrator_persona_version_id
            and original.narrator_persona_version_id != "No_Data"
            else (row.narrator_persona_version_id or "No_Data")
        )
        owner_uid, data_origin = _resolve_owner_uid_and_origin(db, narrator_persona_id, owner_uid_cache)

        s_total_diff = None
        if row.s_total is not None and original is not None and original.s_total is not None:
            s_total_diff = row.s_total - original.s_total

        corrected_result = row.result or {}
        original_result = (original.result or {}) if original else {}

        pairs.append(
            build_envelope(
                dataset_layer="correction",
                source_collection="nazokake_items",
                source_doc_id=row.doc_id,
                narrator_persona_id=narrator_persona_id,
                narrator_persona_version_id=narrator_persona_version_id,
                data_origin=data_origin,
                owner_uid=owner_uid,
                created_at=row.created_at or "",
                payload={
                    "odai": row.odai,
                    "original_toku": original_result.get("toku", ""),
                    "original_kokoro": original_result.get("kokoro", ""),
                    "corrected_toku": corrected_result.get("toku", ""),
                    "corrected_kokoro": corrected_result.get("kokoro", ""),
                    "s_total_diff": s_total_diff,
                },
            )
        )
    return pairs

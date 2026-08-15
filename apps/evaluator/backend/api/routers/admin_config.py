"""api/routers/admin_config.py
===============================
Ⅳ 生成部分のデフォルト設定(Phase4)。ペルソナの3段階ライフサイクル管理。

GET    /personas       : ハードコード初期値(nazokake_core.personas.PERSONAS)と
                          Firestore(persona_overrides)をマージして返す。
DELETE /personas/{id}  : 上書きを削除し(③クリア)、ハードコード初期値へフォールバック。
PUT    /personas/{id}  : ①登録(時限)/②上書き(永続)を作成・更新する。

【時限ライフサイクルの遅延評価(★要件の核心)】専用のバッチ・スケジューラを
一切持たない。GET /personas が呼ばれるたびに、各overrideドキュメントについて
「mode=="temporary" かつ expires_at<=now」かを評価し、失効していればマージ対象
から除外した上で、BackgroundTasksを使ってレスポンス送出後にFirestoreから
ベストエフォート削除する(リクエストのレイテンシには一切影響させない)。
判定・マージのロジック本体(merge_persona_overrides)はI/Oを含まない純粋関数
としてnazokake_core.personas側に置き、apps/persona_main_function側の生成ホットパス
(get_personas())とこのAPIの両方から再利用する(ロジックの二重実装を防ぐ、
SSoT原則)。

管理画面は常に最新の状態を見たいため、get_personas()のTTLキャッシュ(最大5分の
反映遅延)を経由せず、fetch_persona_overrides_sync()でFirestoreを都度直接読む
(生成のホットパスと違い、管理画面のアクセス頻度は低く鮮度を優先してよい)。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.deps import get_db, handle_exceptions, verify_admin_token
from models.schemas import (
    PersonaConfigDeleteResponse,
    PersonaConfigItem,
    PersonaConfigListResponse,
    PersonaConfigUpdateRequest,
    PersonaConfigUpdateResponse,
)
from nazokake_core.personas import (
    PERSONA_OVERRIDES_COLLECTION,
    PERSONAS,
    cleanup_expired_persona_overrides_sync,
    fetch_persona_overrides_sync,
    merge_persona_overrides,
)

router = APIRouter()

# ①登録(時限)のプリセット期間。②上書き(永続)は"permanent"でNone(expires_atを
# 持たない)。フロントエンドのラジオボタン("24時間"/"3日間"/"永続適用")と
# 1対1で対応させる(クライアントに絶対時刻を計算させない=クロックスキュー耐性)。
_DURATION_PRESETS: dict[str, timedelta | None] = {
    "24h": timedelta(hours=24),
    "3d": timedelta(days=3),
    "permanent": None,
}


def _build_persona_config_items(
    overrides_docs: dict[str, dict],
) -> tuple[list[PersonaConfigItem], list[str]]:
    """PERSONAS(ハードコード)+overrides_docsから、管理画面表示用のアイテム一覧を
    組み立てる。merge_persona_overrides()と同じ失効判定を行い、表示上も
    「デフォルト」として扱う(=UIに失効した時限設定が見えてしまうことを防ぐ)。

    戻り値: (表示用アイテム一覧, 失効していたため削除すべきドキュメントIDのリスト)。
    """
    now = datetime.now(timezone.utc)
    merged, expired_ids = merge_persona_overrides(overrides_docs, now=now)

    items: list[PersonaConfigItem] = []
    for persona_id in sorted(PERSONAS.keys()):
        entry = merged[persona_id]
        doc = overrides_docs.get(str(persona_id))

        # このpersona_idに対応するoverrideが「有効(失効していない)」かどうかは、
        # mergeの結果(entryがハードコード値と一致するか)ではなく、
        # 「overrides_docsに存在し、かつ失効リストに入っていないか」で判定する
        # (名前もプロンプトも偶然ハードコード値と同じ、というレアケースでも
        # 誤判定しないようにするため)。
        is_active_override = doc is not None and str(persona_id) not in expired_ids

        if is_active_override:
            mode = doc.get("mode", "permanent")
            items.append(
                PersonaConfigItem(
                    persona_id=persona_id,
                    name=entry["name"],
                    prompt=entry["prompt"],
                    mode="temporary" if mode == "temporary" else "permanent",
                    expires_at=doc.get("expires_at") if mode == "temporary" else None,
                    updated_at=doc.get("updated_at"),
                    updated_by=doc.get("updated_by"),
                )
            )
        else:
            items.append(
                PersonaConfigItem(
                    persona_id=persona_id,
                    name=entry["name"],
                    prompt=entry["prompt"],
                    mode="default",
                )
            )

    return items, expired_ids


@router.get("/personas", response_model=PersonaConfigListResponse)
@handle_exceptions
async def list_persona_configs(
    background_tasks: BackgroundTasks,
    admin_token: dict = Depends(verify_admin_token),
    db=Depends(get_db),
):
    overrides_docs = await asyncio.to_thread(fetch_persona_overrides_sync, db)
    items, expired_ids = _build_persona_config_items(overrides_docs)

    if expired_ids:
        # 【★遅延評価による自動掃除】レスポンスは失効分を除外した状態で即座に
        # 返す。実際のFirestoreドキュメント削除はBackgroundTasksへ委譲し、
        # リクエストのレイテンシには一切影響させない(ベストエフォート、
        # 削除に失敗しても次回のGETで再度同じ判定・再試行になるだけで実害なし)。
        background_tasks.add_task(cleanup_expired_persona_overrides_sync, db, expired_ids)

    return PersonaConfigListResponse(personas=items)


@router.put("/personas/{persona_id}", response_model=PersonaConfigUpdateResponse)
@handle_exceptions
async def update_persona_config(
    persona_id: int,
    req: PersonaConfigUpdateRequest,
    admin_token: dict = Depends(verify_admin_token),
    db=Depends(get_db),
):
    """①登録(時限、duration_preset="24h"/"3d")・②上書き(永続、"permanent")の
    両方をこのエンドポイントで扱う(モードの違いはexpires_at/mode文字列の差だけで、
    Firestoreへの書き込み経路自体は共通のため)。
    """
    if persona_id not in PERSONAS:
        raise HTTPException(status_code=404, detail=f"不明なpersona_id: {persona_id}")

    duration = _DURATION_PRESETS[req.duration_preset]
    now = datetime.now(timezone.utc)
    mode = "permanent" if duration is None else "temporary"
    expires_at = (now + duration).isoformat() if duration is not None else None

    payload = {
        "prompt": req.prompt,
        "mode": mode,
        "expires_at": expires_at,
        "updated_at": now.isoformat(),
        "updated_by": admin_token.get("uid", "unknown"),
    }
    if req.name:
        payload["name"] = req.name

    def _write_sync():
        db.collection(PERSONA_OVERRIDES_COLLECTION).document(str(persona_id)).set(
            payload, merge=True
        )

    await asyncio.to_thread(_write_sync)

    return PersonaConfigUpdateResponse(
        status="success", persona_id=persona_id, mode=mode, expires_at=expires_at
    )


@router.delete("/personas/{persona_id}", response_model=PersonaConfigDeleteResponse)
@handle_exceptions
async def delete_persona_config(
    persona_id: int,
    admin_token: dict = Depends(verify_admin_token),
    db=Depends(get_db),
):
    """③クリア: Firestoreの上書きドキュメントを削除し、ハードコード初期値へ
    フォールバックさせる(ドキュメントが元々存在しない場合も冪等に成功扱いにする、
    「既にクリア済みの状態を再度クリアする」ことはエラーではないため)。
    """
    if persona_id not in PERSONAS:
        raise HTTPException(status_code=404, detail=f"不明なpersona_id: {persona_id}")

    def _delete_sync():
        db.collection(PERSONA_OVERRIDES_COLLECTION).document(str(persona_id)).delete()

    await asyncio.to_thread(_delete_sync)

    return PersonaConfigDeleteResponse(status="success", persona_id=persona_id)

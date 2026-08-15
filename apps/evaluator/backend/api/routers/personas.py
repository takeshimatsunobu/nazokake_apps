"""
api/routers/personas.py
==========================
persona_feature_plan_v3.md Phase6 §7.1: マイペルソナAPI(9エンドポイント)。

GET    /v1/personas                 : 組み込み+自分のペルソナ一覧(sort_order順)
GET    /v1/personas/schema          : 設定項目定義+ツールチップ
POST   /v1/personas/draft           : 名前からGeminiで初期設定を生成(保存しない)
POST   /v1/personas                 : 新規作成(上限5件)
PATCH  /v1/personas/{id}            : 新バージョン追加
DELETE /v1/personas/{id}            : 論理削除
PUT    /v1/personas/order           : 並び順の一括更新
POST   /v1/personas/transfer-code   : 引き継ぎコード発行
POST   /v1/personas/transfer        : 引き継ぎコード適用

【認証・認可(§6/§6.2)】Firebase匿名認証の適用範囲を、掲示板投稿のみから
ペルソナ関連API全般へ拡張する。GET /schema 以外の全エンドポイントは
Depends(verify_user_token)を要求する。所有者判定は必ずFirebase UID
(decoded_token["uid"])で行い、リクエストボディのuser_slug等のクライアント
自己申告値は使わない。

    参照可: is_builtin == true ∪ owner_uid == 自分
    更新可: owner_uid == 自分
    削除可: owner_uid == 自分 かつ is_deletable == true ← 満たさなければ403
    並替可: 自分が所有するペルソナのみ(組み込みの並び順はグローバル共有のため
            ユーザー操作の対象外とする、実装時の追加判断。詳細はモジュール末尾
            のコメント参照)

【penalty.py(段階的ブロック)の適用(§7.5-5)】Gemini呼び出しを伴う/draftは
毎回ブロック判定+カウント。/personas(作成)は上限5件を超える作成試行の
繰り返しのみをカウント対象とする(正規利用で上限に達しただけのユーザーを
誤って締め出さないため)。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db, verify_user_token
from models.persona_schemas import (
    NarratorPersonaItem,
    NarratorPersonaListResponse,
    PersonaCreateRequest,
    PersonaDeleteResponse,
    PersonaDraftRequest,
    PersonaDraftResponse,
    PersonaMutationResponse,
    PersonaOrderRequest,
    PersonaOrderResponse,
    PersonaSchemaField,
    PersonaSchemaResponse,
    PersonaUpdateRequest,
    TransferCodeApplyRequest,
    TransferCodeApplyResponse,
    TransferCodeIssueResponse,
)
from nazokake_core import narrator_personas
from services.penalty import check_block_status, record_route_b
from services.persona_draft import generate_persona_draft
from services.persona_transfer import TransferCodeError, apply_transfer_code, issue_transfer_code

router = APIRouter()

MAX_PERSONAS_PER_OWNER = 5


def _to_item(db, data: dict) -> NarratorPersonaItem:
    version_id = data.get("current_version_id", "")
    # 【persona_feature_plan_v3.md Phase7で追加】編集フォームのプリフィル用に
    # settingsを同梱する。バージョン文書が見つからない(想定外の状態)場合でも
    # 一覧取得自体は失敗させず、settings=Noneのまま返す。
    version = narrator_personas.get_persona_version(db, version_id) if version_id else None
    settings = version.get("settings") if version else None

    return NarratorPersonaItem(
        persona_id=data["persona_id"],
        display_name=data.get("display_name", ""),
        owner_uid=data.get("owner_uid", ""),
        owner_display_name=data.get("owner_display_name"),
        base_persona_id=data.get("base_persona_id"),
        is_builtin=bool(data.get("is_builtin", False)),
        is_deletable=bool(data.get("is_deletable", True)),
        is_visible=bool(data.get("is_visible", True)),
        current_version_id=version_id,
        sort_order=int(data.get("sort_order", 0)),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        settings=settings,
    )


def _require_block_status_ok(db, uid: str) -> None:
    """penalty.pyのブロック判定ゲート。ブロック中は429で拒否する。"""
    status = check_block_status(db, uid)
    if status.blocked:
        raise HTTPException(
            status_code=429,
            detail=f"利用回数の上限に達したため一時的に制限されています({status.blocked_until}まで)。",
        )


@router.get("/v1/personas", response_model=NarratorPersonaListResponse)
async def list_personas(
    user_token: dict = Depends(verify_user_token),
    db=Depends(get_db),
):
    """§6.2「参照可: is_builtin==true ∪ owner_uid==自分」。sort_order順。"""
    uid = user_token["uid"]
    items = [_to_item(db, p) for p in narrator_personas.list_visible_personas(db, uid)]
    return NarratorPersonaListResponse(personas=items)


@router.get("/v1/personas/schema", response_model=PersonaSchemaResponse)
async def get_personas_schema():
    """§3.2の設定項目定義+ツールチップ本文。認証不要(静的な参照データ)。"""
    fields = [
        PersonaSchemaField(
            key="display_name", type="string", applies_to="both",
            tooltip="このペルソナの呼び名です",
        ),
        PersonaSchemaField(
            key="prompt", type="string", applies_to="both",
            tooltip="AIに「あなたは誰か」を教える文章。人格の核になります",
        ),
        PersonaSchemaField(
            key="first_person", type="string", applies_to="both",
            tooltip="一人称(僕・私・わし など)",
        ),
        PersonaSchemaField(
            key="speech_style", type="string", applies_to="both",
            tooltip="語尾や口調の癖",
        ),
        PersonaSchemaField(
            key="tone", type="enum", applies_to="both",
            tooltip="全体の雰囲気",
        ),
        PersonaSchemaField(
            key="favorite_topics", type="list[string]", applies_to="both",
            tooltip="得意なお題のジャンル",
        ),
        PersonaSchemaField(
            key="taboo", type="list[string]", applies_to="both",
            tooltip="触れさせたくない話題",
        ),
        PersonaSchemaField(
            key="thinking_level", type="enum", applies_to="gemini",
            tooltip="AIがどれくらいじっくり考えるか",
        ),
        PersonaSchemaField(
            key="temperature", type="float", applies_to="elyza",
            tooltip="発想の飛躍度",
        ),
    ]
    return PersonaSchemaResponse(fields=fields)


@router.post("/v1/personas/draft", response_model=PersonaDraftResponse)
async def draft_persona(
    req: PersonaDraftRequest,
    user_token: dict = Depends(verify_user_token),
    db=Depends(get_db),
):
    """§7.4: 名前からGeminiで初期設定を生成する(保存しない)。"""
    uid = user_token["uid"]
    _require_block_status_ok(db, uid)
    # 【§7.5-5】Gemini呼び出しを伴う都度カウントする(呼び出し自体がコストの
    # かかる操作であり、成功/フェイルセーフいずれの結果でも対象とする)。
    record_route_b(db, uid)

    settings, is_fallback = await generate_persona_draft(req.display_name)
    return PersonaDraftResponse(settings=settings, is_fallback=is_fallback)


@router.post("/v1/personas", response_model=PersonaMutationResponse)
async def create_persona(
    req: PersonaCreateRequest,
    user_token: dict = Depends(verify_user_token),
    db=Depends(get_db),
):
    """§6: 新規作成(1UIDあたり上限5件)。"""
    uid = user_token["uid"]
    _require_block_status_ok(db, uid)

    if req.base_persona_id is not None:
        base = narrator_personas.get_persona(db, req.base_persona_id)
        if base is None or not (base.get("is_builtin") or base.get("owner_uid") == uid):
            raise HTTPException(status_code=400, detail="base_persona_idが不正です。")

    existing_count = narrator_personas.count_owned_personas(db, uid)
    if existing_count >= MAX_PERSONAS_PER_OWNER:
        # 【§7.5-5】上限を超える作成試行の繰り返しのみをカウント対象とする
        # (正規利用で上限に達しただけのユーザーを誤って締め出さないため)。
        record_route_b(db, uid)
        raise HTTPException(
            status_code=400,
            detail=f"マイペルソナは1人あたり最大{MAX_PERSONAS_PER_OWNER}件までです。",
        )

    sort_order = narrator_personas.next_sort_order_for_new_persona(db, uid)
    persona_id, version_id = narrator_personas.create_persona(
        db,
        owner_uid=uid,
        settings=req.settings.model_dump(),
        display_name=req.settings.display_name,
        base_persona_id=req.base_persona_id,
        is_builtin=False,
        is_deletable=True,
        is_visible=True,
        sort_order=sort_order,
    )
    return PersonaMutationResponse(persona_id=persona_id, version_id=version_id)


@router.patch("/v1/personas/{persona_id}", response_model=PersonaMutationResponse)
async def update_persona(
    persona_id: str,
    req: PersonaUpdateRequest,
    user_token: dict = Depends(verify_user_token),
    db=Depends(get_db),
):
    """§6.2「更新可: owner_uid==自分」。新バージョンを追加する(§3.3)。"""
    uid = user_token["uid"]
    persona = narrator_personas.get_persona(db, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="指定されたペルソナが見つかりません。")
    if persona.get("owner_uid") != uid:
        raise HTTPException(status_code=403, detail="このペルソナを更新する権限がありません。")

    version_id = narrator_personas.save_persona_settings(
        db, persona_id, req.settings.model_dump()
    )
    return PersonaMutationResponse(persona_id=persona_id, version_id=version_id)


@router.delete("/v1/personas/{persona_id}", response_model=PersonaDeleteResponse)
async def delete_persona(
    persona_id: str,
    user_token: dict = Depends(verify_user_token),
    db=Depends(get_db),
):
    """§6.2「削除可: owner_uid==自分 かつ is_deletable==true ← 満たさなければ403」。"""
    uid = user_token["uid"]
    persona = narrator_personas.get_persona(db, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="指定されたペルソナが見つかりません。")
    if persona.get("owner_uid") != uid or not persona.get("is_deletable", False):
        raise HTTPException(status_code=403, detail="このペルソナを削除する権限がありません。")

    narrator_personas.soft_delete_persona(db, persona_id)
    return PersonaDeleteResponse(persona_id=persona_id, deleted=True)


@router.put("/v1/personas/order", response_model=PersonaOrderResponse)
async def reorder_personas(
    req: PersonaOrderRequest,
    user_token: dict = Depends(verify_user_token),
    db=Depends(get_db),
):
    """§6.2「並替可: 自分から見える範囲のみ」。

    【実装時の追加判断】「自分から見える範囲」は文言上は組み込み(is_builtin)を
    含むが、組み込みのsort_orderは全ユーザー共有のグローバルな値であり、
    1ユーザーの並替操作で他ユーザー全員の表示順を書き換えてしまうことは
    §8.1のUI設計(組み込み10体は「編集トグルなし」の固定セクション)の意図にも
    反する。そのため本APIは「自分が所有するペルソナ(owner_uid==自分)のみ」に
    対象を限定し、リクエストに組み込みIDが含まれる場合は403とする。
    """
    uid = user_token["uid"]
    for persona_id in req.ordered_persona_ids:
        persona = narrator_personas.get_persona(db, persona_id)
        if persona is None or persona.get("owner_uid") != uid:
            raise HTTPException(
                status_code=403,
                detail=f"persona_id={persona_id!r} は並び替えの対象外です。",
            )

    narrator_personas.reorder_personas(db, req.ordered_persona_ids)
    return PersonaOrderResponse(ordered_persona_ids=req.ordered_persona_ids)


@router.post("/v1/personas/transfer-code", response_model=TransferCodeIssueResponse)
async def issue_persona_transfer_code(
    user_token: dict = Depends(verify_user_token),
    db=Depends(get_db),
):
    """§6.1: 引き継ぎコード発行(24時間有効・1回使い切り)。"""
    uid = user_token["uid"]
    code, expires_at = issue_transfer_code(db, uid)
    return TransferCodeIssueResponse(code=code, expires_at=expires_at)


@router.post("/v1/personas/transfer", response_model=TransferCodeApplyResponse)
async def apply_persona_transfer_code(
    req: TransferCodeApplyRequest,
    user_token: dict = Depends(verify_user_token),
    db=Depends(get_db),
):
    """§6.1: 引き継ぎコードを適用し、旧UID配下のペルソナを現在のUIDへ移管する。"""
    uid = user_token["uid"]
    try:
        transferred_count = apply_transfer_code(db, req.code, uid)
    except TransferCodeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return TransferCodeApplyResponse(transferred_count=transferred_count, new_owner_uid=uid)

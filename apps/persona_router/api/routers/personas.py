"""
api/routers/personas.py
==========================
GET /v1/personas: フロントエンドのペルソナ選択UIが表示用のid/nameだけを
取得するための読み取り専用エンドポイント。

nazokake_core.personas.PERSONAS(SSoT)をそのまま公開すると生成プロンプトの
内部詳細(prompt本文)まで露出してしまうため、表示に必要なid/nameのみへ
絞り込んで返す(models/schemas.py::PersonaListItemのdocstring参照)。

【Phase4】ハードコードのPERSONASを直接参照する代わりにget_personas(db)を
呼ぶことで、管理コクピット(Ⅳ生成設定ペイン)から名前が上書きされた場合、
このエンドユーザー向けの選択UIにもその名前が反映される(TTLキャッシュ済み)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_db
from models.schemas import PersonaListItem, PersonaListResponse
from nazokake_core.personas import get_personas

router = APIRouter()


@router.get("/v1/personas", response_model=PersonaListResponse)
async def list_personas(db=Depends(get_db)):
    items = [
        PersonaListItem(persona_id=pid, name=entry["name"])
        for pid, entry in sorted(get_personas(db).items())
    ]
    return PersonaListResponse(personas=items)

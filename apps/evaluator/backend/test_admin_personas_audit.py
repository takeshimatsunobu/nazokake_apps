"""test_admin_personas_audit.py
=================================
改修要件: 管理コクピットへの全ペルソナ監査テーブル配備(GET /v1/admin/personas)の
単体テスト。narrator_personas.list_all_personas_for_admin()が論理削除・非表示・
ビルトインを問わず全件を返すこと、ルーターがsettings(prompt/tone/first_person)を
正しく展開して返すことを検証する。Firestore実サービスへは接続しない。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from api.routers.personas import list_all_personas_for_admin_audit
from nazokake_core import narrator_personas


def _make_snapshot(data: dict) -> MagicMock:
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = data
    return snap


def test_list_all_personas_for_admin_includes_deleted_and_hidden():
    """narrator_personas.list_all_personas_for_admin()は、他の一覧系関数と異なり
    削除済み(deleted_at設定済み)・非表示(is_visible=False)も含め無条件に返すこと。"""
    docs_data = [
        {"persona_id": "a", "deleted_at": None, "is_visible": True},
        {"persona_id": "b", "deleted_at": "2026-01-01T00:00:00Z", "is_visible": True},
        {"persona_id": "c", "deleted_at": None, "is_visible": False},
    ]
    query = MagicMock()
    query.stream.return_value = [_make_snapshot(d) for d in docs_data]
    db = MagicMock()
    db.collection.return_value = query

    result = narrator_personas.list_all_personas_for_admin(db)
    ids = {p["persona_id"] for p in result}

    assert ids == {"a", "b", "c"}


def test_list_all_personas_for_admin_returns_empty_list_on_firestore_failure():
    """Firestore障害時は例外を伝播させず空リストへ縮退すること(ディープ監査#4と
    同じフェイルセーフ方針)。"""
    db = MagicMock()
    db.collection.side_effect = Exception("接続エラー")

    result = narrator_personas.list_all_personas_for_admin(db)

    assert result == []


@pytest.mark.anyio
async def test_admin_personas_audit_endpoint_returns_full_fields():
    """GET /v1/admin/personas相当のルーター関数が、persona_id/created_at/
    author_slug/name/first_person/tone/system_prompt/usage_count/
    zabuton_count/is_deletedの全フィールドを正しく組み立てて返すこと。"""
    db = MagicMock()
    persona_docs = [
        {
            "persona_id": "p-1",
            "created_at": "2026-08-01T00:00:00+00:00",
            "owner_uid": "uid-1",
            "display_name": "テストペルソナ",
            "current_version_id": "p-1__v1",
            "usage_count": 5,
            "zabuton_count": 2,
            "deleted_at": None,
        },
        {
            "persona_id": "p-2",
            "created_at": "2026-08-02T00:00:00+00:00",
            "owner_uid": "uid-2",
            "display_name": "削除済みペルソナ",
            "current_version_id": "p-2__v1",
            "usage_count": 0,
            "zabuton_count": 0,
            "deleted_at": "2026-08-03T00:00:00+00:00",
        },
    ]
    version_docs = {
        "p-1__v1": {"settings": {"prompt": "プロンプト1", "tone": "warm", "first_person": "わし"}},
        "p-2__v1": {"settings": {"prompt": "プロンプト2", "tone": "cool", "first_person": "俺"}},
    }

    with patch(
        "api.routers.personas.narrator_personas.list_all_personas_for_admin",
        return_value=persona_docs,
    ), patch(
        "api.routers.personas.narrator_personas.get_persona_version",
        side_effect=lambda db, vid: version_docs.get(vid),
    ):
        response = await list_all_personas_for_admin_audit(admin_token={"uid": "admin-1"}, db=db)

    assert len(response.personas) == 2
    first, second = response.personas

    assert first.persona_id == "p-1"
    assert first.created_at == "2026-08-01T00:00:00+00:00"
    assert first.author_slug == "uid-1"
    assert first.name == "テストペルソナ"
    assert first.first_person == "わし"
    assert first.tone == "warm"
    assert first.system_prompt == "プロンプト1"
    assert first.usage_count == 5
    assert first.zabuton_count == 2
    assert first.is_deleted is False

    assert second.persona_id == "p-2"
    assert second.is_deleted is True


@pytest.mark.anyio
async def test_admin_personas_audit_endpoint_handles_missing_version_gracefully():
    """current_version_idに対応するversion文書が見つからない場合でも、
    system_prompt等を空文字にフォールバックしてクラッシュしないこと。"""
    db = MagicMock()
    persona_docs = [
        {
            "persona_id": "p-orphan",
            "created_at": "2026-08-01T00:00:00+00:00",
            "owner_uid": "uid-1",
            "display_name": "孤立ペルソナ",
            "current_version_id": "missing-version",
            "usage_count": 0,
            "zabuton_count": 0,
            "deleted_at": None,
        }
    ]

    with patch(
        "api.routers.personas.narrator_personas.list_all_personas_for_admin",
        return_value=persona_docs,
    ), patch(
        "api.routers.personas.narrator_personas.get_persona_version",
        return_value=None,
    ):
        response = await list_all_personas_for_admin_audit(admin_token={"uid": "admin-1"}, db=db)

    assert len(response.personas) == 1
    assert response.personas[0].system_prompt == ""
    assert response.personas[0].tone == ""
    assert response.personas[0].first_person == ""

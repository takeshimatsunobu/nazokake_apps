"""test_generate_persona_resolution.py
========================================
persona_feature_plan_v3.md Phase5「生成パスへの記録」の単体テスト。

apps/evaluator/backend/test_fail_closed.py と同じ配置規約(アプリディレクトリ直下、
`cd apps/persona_main_function && pytest test_generate_persona_resolution.py`で実行)。
Firestore/Gemini実サービスへは接続しない(unittest.mockでFirestoreドキュメント
スナップショットを模擬する)。

検証観点:
1. GenerateRoutedRequest.persona_id が int/str いずれの入力もstrへ正規化される。
2. _resolve_persona_for_generation() がビルトイン("1"〜"10")を正しく解決する。
3. _resolve_persona_for_generation() がマイペルソナ(UUID文字列)を正しく解決する。
4. _resolve_persona_for_generation() が不明なpersona_idに対し404を送出する
   (persona_feature_plan_v3.md §7.3: ID:1への黙示フォールバックは廃止)。
5. _compose_persona_prompt() がビルトイン(prompt onlyの2キー)の挙動を変えず、
   マイペルソナの口調・トーン設定を追記する。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api.routers.generate import _resolve_persona_for_generation
from models.schemas import GenerateRoutedRequest
from nazokake_core.personas import PERSONAS
from services.step2_generation import _compose_persona_prompt


def _make_snapshot(exists: bool, data: dict | None = None) -> MagicMock:
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data
    return snap


def test_persona_id_accepts_int_and_normalizes_to_str():
    req = GenerateRoutedRequest(odai="テスト", persona_id=3, client_uuid="u1")
    assert req.persona_id == "3"
    assert isinstance(req.persona_id, str)

    req2 = GenerateRoutedRequest(odai="テスト", persona_id="custom-uuid", client_uuid="u1")
    assert req2.persona_id == "custom-uuid"


def test_resolve_builtin_persona_uses_hardcoded_dict_when_firestore_unavailable():
    # get_personas(db)はFirestore接続に失敗するとハードコードのPERSONASへ
    # フォールバックする(nazokake_core/personas.py::get_personas参照)。
    # MagicMockはdb.collection(...).stream()の反復でTypeErrorを起こすため、
    # このフォールバック経路を自然に踏む。
    db = MagicMock()
    resolved = _resolve_persona_for_generation(db, "3")
    assert resolved.data_origin == "builtin"
    assert resolved.display_name == PERSONAS[3]["name"]
    assert resolved.settings["prompt"] == PERSONAS[3]["prompt"]
    assert resolved.version_id.startswith("3__")


def test_resolve_custom_persona_reads_narrator_personas_and_versions():
    db = MagicMock()
    persona_doc = {
        "persona_id": "my-uuid-1",
        "owner_uid": "uid-abc",
        "display_name": "テストペルソナ",
        "is_builtin": False,
        "is_deletable": True,
        "current_version_id": "my-uuid-1__deadbeef12345678",
        "deleted_at": None,
    }
    version_doc = {
        "version_id": "my-uuid-1__deadbeef12345678",
        "settings": {
            "display_name": "テストペルソナ",
            "prompt": "テスト用のプロンプト本文。",
            "first_person": "わし",
            "speech_style": "語尾に「じゃ」を付ける",
            "tone": "warm",
            "favorite_topics": ["科学"],
            "taboo": [],
            "thinking_level": "medium",
        },
    }

    def _collection(name):
        col = MagicMock()
        if name == "narrator_personas":
            col.document.return_value.get.return_value = _make_snapshot(True, persona_doc)
        elif name == "narrator_persona_versions":
            col.document.return_value.get.return_value = _make_snapshot(True, version_doc)
        return col

    db.collection.side_effect = _collection

    resolved = _resolve_persona_for_generation(db, "my-uuid-1")
    assert resolved.data_origin == "custom"
    assert resolved.display_name == "テストペルソナ"
    assert resolved.version_id == "my-uuid-1__deadbeef12345678"
    assert resolved.settings["first_person"] == "わし"


def test_resolve_unknown_persona_id_raises_404_not_fallback():
    db = MagicMock()

    def _collection(name):
        col = MagicMock()
        col.document.return_value.get.return_value = _make_snapshot(False, None)
        return col

    db.collection.side_effect = _collection

    with pytest.raises(HTTPException) as exc_info:
        _resolve_persona_for_generation(db, "does-not-exist")
    assert exc_info.value.status_code == 404


def test_compose_persona_prompt_builtin_unchanged():
    builtin = {"name": PERSONAS[1]["name"], "prompt": PERSONAS[1]["prompt"]}
    assert _compose_persona_prompt(builtin) == PERSONAS[1]["prompt"]


def test_compose_persona_prompt_custom_appends_voice_settings():
    custom = {
        "prompt": "ベースの人格描写。",
        "first_person": "僕",
        "speech_style": "です・ます調",
        "tone": "gentle",
        "favorite_topics": ["音楽", "料理"],
        "taboo": ["政治"],
        "thinking_level": "low",
    }
    composed = _compose_persona_prompt(custom)
    assert composed.startswith("ベースの人格描写。")
    assert "一人称: 僕" in composed
    assert "語尾・口調の癖: です・ます調" in composed
    assert "全体の雰囲気: gentle" in composed
    assert "音楽、料理" in composed
    assert "政治" in composed

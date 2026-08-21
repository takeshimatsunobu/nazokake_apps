"""test_timeline_persona_id_coercion.py
========================================
「マイペルソナ」画面(apps/evaluator/frontend/public/personas/index.html)の
GET /v1/timeline が本番・ローカル開発の両方で500 Internal Server Errorに
なっていた不具合の回帰テスト。

【根本原因】models/persona_schemas.py::TimelineItem.persona_id は str固定
(マイペルソナのUUID文字列も保持するための設計)だが、str化される前の時期に
書き込まれた旧ドキュメントはFirestore上でpersona_idがint(例: 2)のまま
保存されており、Pydantic v2はint→strの暗黙変換を行わないため
ValidationError(500)になっていた。api/routers/timeline.py::_to_timeline_item()
で明示的にstr化するよう修正した。

このテストはFirestore/Gemini実サービスへは接続しない(モックデータを直接渡す)。
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = Path(__file__).resolve().parent
_SHARED_CORE_ROOT = _PROJECT_ROOT / "packages" / "shared_core"
for _p in (_PROJECT_ROOT, _BACKEND_ROOT, _SHARED_CORE_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from api.routers.timeline import _to_timeline_item  # noqa: E402


def _base_doc(**overrides) -> dict:
    doc = {
        "doc_id": "doc-1",
        "odai": "お題",
        "persona_id": "1",
        "route": "A",
        "toku": "解き",
        "kokoro": "こころ",
        "nazokake_text": "本文",
        "is_valid_for_training": True,
        "created_at": "2026-08-21T00:00:00+00:00",
    }
    doc.update(overrides)
    return doc


def test_legacy_int_persona_id_is_coerced_to_string():
    """str化以前に書き込まれた旧ドキュメント(persona_idがint)でもValidationError
    にならず、正しくstrへ変換されること。"""
    item = _to_timeline_item(_base_doc(persona_id=2))
    assert item.persona_id == "2"
    assert isinstance(item.persona_id, str)


def test_custom_persona_uuid_string_passes_through_unchanged():
    """マイペルソナのUUID文字列(str)は従来通りそのまま保持されること
    (この修正による回帰が無いことの確認)。"""
    item = _to_timeline_item(_base_doc(persona_id="fdca0a20-f6fc-4920-93a2-bf1355fe551e"))
    assert item.persona_id == "fdca0a20-f6fc-4920-93a2-bf1355fe551e"


def test_numeric_string_persona_id_passes_through_unchanged():
    item = _to_timeline_item(_base_doc(persona_id="4"))
    assert item.persona_id == "4"


def test_missing_zabuton_count_defaults_to_zero():
    """zabuton_countキー自体が無い旧ドキュメントでも、デフォルト値0が適用される
    こと(既存の防御ロジックの回帰確認)。"""
    doc = _base_doc(persona_id=1)
    doc.pop("zabuton_count", None)
    item = _to_timeline_item(doc)
    assert item.zabuton_count == 0

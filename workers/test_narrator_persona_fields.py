"""test_narrator_persona_fields.py
====================================
docs/persona_feature_plan_v3.md §12「ELYZAワーカーがnarrator_persona_id等を
記録しない」既知ギャップの対応検証。

ondemand_elyza_worker.py::_resolve_narrator_persona_fields()の単体テスト。
Firestore/Ollama等の実サービスへは接続しない(unittest.mockでdbを模擬)。

cd (リポジトリルート) && .venv/Scripts/python.exe -m pytest workers/test_narrator_persona_fields.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
for _p in (BASE_DIR, BASE_DIR / "workers", BASE_DIR / "apps" / "evaluator" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ondemand_elyza_worker as worker  # noqa: E402
from nazokake_core.personas import PERSONAS  # noqa: E402


def _make_snapshot(exists: bool, data: dict | None = None) -> MagicMock:
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data
    return snap


def test_builtin_persona_id_int_resolves_correctly():
    db = MagicMock()  # Firestore接続不可 → get_personas()内部でハードコードPERSONASへフォールバック
    result = worker._resolve_narrator_persona_fields(db, 3, None)
    assert result["narrator_persona_id"] == "3"
    assert result["narrator_persona_name"] == PERSONAS[3]["name"]
    assert result["data_origin"] == "builtin"
    assert result["narrator_persona_version_id"].startswith("3__")


def test_builtin_persona_id_str_resolves_correctly():
    db = MagicMock()
    result = worker._resolve_narrator_persona_fields(db, "7", None)
    assert result["narrator_persona_id"] == "7"
    assert result["narrator_persona_name"] == PERSONAS[7]["name"]
    assert result["data_origin"] == "builtin"


def test_version_id_snapshot_is_preferred_over_recomputation():
    db = MagicMock()
    result = worker._resolve_narrator_persona_fields(db, 1, "1__snapshot1234567")
    assert result["narrator_persona_version_id"] == "1__snapshot1234567"


def test_persona_id_none_falls_back_to_no_data():
    db = MagicMock()
    result = worker._resolve_narrator_persona_fields(db, None, None)
    assert result == worker._NARRATOR_PERSONA_FALLBACK


def test_invalid_persona_id_falls_back_to_no_data():
    db = MagicMock()

    def _collection(name):
        col = MagicMock()
        col.document.return_value.get.return_value = _make_snapshot(False, None)
        return col

    db.collection.side_effect = _collection
    result = worker._resolve_narrator_persona_fields(db, "not-a-real-id", None)
    assert result["data_origin"] == "no_data"
    assert result["narrator_persona_id"] == "No_Data"


def test_custom_persona_uuid_resolves_via_narrator_personas():
    db = MagicMock()
    custom_doc = {
        "persona_id": "custom-uuid-1",
        "display_name": "テストペルソナ",
        "current_version_id": "custom-uuid-1__abcdef0123456789",
        "deleted_at": None,
    }

    def _collection(name):
        col = MagicMock()
        if name == "narrator_personas":
            col.document.return_value.get.return_value = _make_snapshot(True, custom_doc)
        return col

    db.collection.side_effect = _collection
    result = worker._resolve_narrator_persona_fields(db, "custom-uuid-1", None)
    assert result["data_origin"] == "custom"
    assert result["narrator_persona_name"] == "テストペルソナ"
    assert result["narrator_persona_version_id"] == "custom-uuid-1__abcdef0123456789"


def test_exception_during_resolution_falls_back_safely():
    db = MagicMock()
    db.collection.side_effect = RuntimeError("Firestore接続不能(テスト用)")
    # get_personas(db)自体は例外を握りつぶしハードコードPERSONASへフォールバックするため、
    # ビルトインID(数字)では成功してしまう。ここでは非数字IDでnarrator_personas.get_persona
    # 経由のFirestoreアクセスが例外を出すケースを検証する。
    result = worker._resolve_narrator_persona_fields(db, "will-blow-up", None)
    assert result == worker._NARRATOR_PERSONA_FALLBACK


def test_scoped_fields_never_receive_narrator_persona_keys():
    """Firestoreスコープ(_ELYZA_JOB_SCOPED_FIELDS)にnarrator_persona_*が
    含まれていないことを確認する(混入するとFirestore書き込みが
    ValueErrorで落ちるため、_process_job側の実装規約として重要)。"""
    for key in worker._NARRATOR_PERSONA_FALLBACK:
        assert key not in worker._ELYZA_JOB_SCOPED_FIELDS

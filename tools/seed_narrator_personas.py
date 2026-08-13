"""
tools/seed_narrator_personas.py
==================================
persona_feature_plan_v3.md Phase4 item2: 組み込み10体(PERSONAS[1..10])と
センチネル"No_Data"を、Firestoreの narrator_personas / narrator_persona_versions
コレクションへ投入する冪等なシードスクリプト。

書き込みは nazokake_core.narrator_personas の create_persona() /
save_persona_settings() の2関数のみを経由する(そのモジュール自身のdocstring
が定める「書き込み口はこの2関数のみ」という制約を、このスクリプトも遵守する)。

冪等性: 対象persona_idのnarrator_personasドキュメントが既に存在する場合は
save_persona_settings()で内容を最新化するのみ(created_at/owner_uid等は
変更しない)。存在しない場合のみcreate_persona()で新規作成する。settingsの
内容が前回実行時と同一であれば、内容ハッシュも同一のため新しいversionは
作られず、実質no-opになる(何度実行しても安全)。

使い方:
    uv run python tools/seed_narrator_personas.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "packages" / "shared_core"))

import firebase_admin  # noqa: E402
from firebase_admin import firestore  # noqa: E402

from nazokake_core.firestore_sync import _ensure_firebase_app  # noqa: E402
from nazokake_core.narrator_personas import (  # noqa: E402
    NARRATOR_PERSONAS_COLLECTION,
    SENTINEL_PERSONA_ID,
    SYSTEM_OWNER_UID,
    create_persona,
    save_persona_settings,
)
from nazokake_core.personas import PERSONAS  # noqa: E402


def _seed_one(db, *, persona_id: str, display_name: str, settings: dict, sort_order: int, is_visible: bool) -> str:
    """1件分の冪等シード処理。戻り値は "created" または "updated"。"""
    doc_ref = db.collection(NARRATOR_PERSONAS_COLLECTION).document(persona_id)
    if doc_ref.get().exists:
        save_persona_settings(db, persona_id, settings)
        return "updated"

    create_persona(
        db,
        owner_uid=SYSTEM_OWNER_UID,
        settings=settings,
        display_name=display_name,
        persona_id=persona_id,
        is_builtin=True,
        is_deletable=False,
        is_visible=is_visible,
        sort_order=sort_order,
    )
    return "created"


def main() -> int:
    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})
    _ensure_firebase_app()
    db = firestore.client()

    results: dict[str, str] = {}

    for pid, entry in sorted(PERSONAS.items()):
        persona_id = str(pid)
        settings = {"display_name": entry["name"], "prompt": entry["prompt"]}
        outcome = _seed_one(
            db,
            persona_id=persona_id,
            display_name=entry["name"],
            settings=settings,
            sort_order=pid,
            is_visible=True,
        )
        results[persona_id] = outcome
        print(f"[seed_narrator_personas] persona_id={persona_id} ({entry['name'][:20]}...): {outcome}")

    # センチネル: narrator_persona_idが未判定であることを表す固定ID。
    # is_visible=Falseで一覧から隠す(§3.1)。
    sentinel_outcome = _seed_one(
        db,
        persona_id=SENTINEL_PERSONA_ID,
        display_name=SENTINEL_PERSONA_ID,
        settings={"display_name": SENTINEL_PERSONA_ID, "prompt": ""},
        sort_order=-1,
        is_visible=False,
    )
    results[SENTINEL_PERSONA_ID] = sentinel_outcome
    print(f"[seed_narrator_personas] persona_id={SENTINEL_PERSONA_ID} (センチネル): {sentinel_outcome}")

    created = sum(1 for v in results.values() if v == "created")
    updated = sum(1 for v in results.values() if v == "updated")
    print(f"[seed_narrator_personas] 完了: created={created} updated={updated} total={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

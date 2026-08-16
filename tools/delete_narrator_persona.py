"""
tools/delete_narrator_persona.py
===================================
本番Firestoreに残存したテスト用narrator_personaドキュメント(および紐づく
narrator_persona_versions)を、名前/owner_uidの完全一致条件で安全に削除する
ための一回性クリーンアップCLI。

【Firestore接続の作法】tools/inspect_firestore_jobs.py冒頭の【絶対制約】に従い、
nazokake_core.firestore_sync._ensure_firebase_app()を経由した既存の初期化
パターン(tools/seed_narrator_personas.py参照)を無改変で再利用する。

【安全策】既定はドライラン(一致件数と内容を表示するのみ、削除しない)。
実際に削除するには --execute を明示的に渡す必要がある。

使い方:
    uv run python tools/delete_narrator_persona.py \
        --display-name "フルE2Eテスト忍者" --owner-uid "e2e-full-popular-uid"
    uv run python tools/delete_narrator_persona.py \
        --display-name "フルE2Eテスト忍者" --owner-uid "e2e-full-popular-uid" --execute
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "packages" / "shared_core"))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import firebase_admin  # noqa: E402
from firebase_admin import firestore  # noqa: E402

from nazokake_core.firestore_sync import _ensure_firebase_app  # noqa: E402
from nazokake_core.narrator_personas import (  # noqa: E402
    NARRATOR_PERSONA_VERSIONS_COLLECTION,
    NARRATOR_PERSONAS_COLLECTION,
)


def _find_matching_personas(db, *, display_name: str | None, owner_uid: str | None) -> list[dict]:
    """display_name完全一致 OR owner_uid完全一致のnarrator_personasドキュメントを集める。
    件数の少なさが分かっている一回性クリーンアップのため、コレクション全件を
    読み取ってPython側でフィルタする(複合OR条件のインデックス要求を避ける)。
    """
    matched: dict[str, dict] = {}
    for doc in db.collection(NARRATOR_PERSONAS_COLLECTION).stream():
        data = doc.to_dict() or {}
        if display_name and data.get("display_name") == display_name:
            matched[doc.id] = data
        if owner_uid and data.get("owner_uid") == owner_uid:
            matched[doc.id] = data
    return [{"doc_id": doc_id, **data} for doc_id, data in matched.items()]


def _find_versions_for_persona(db, persona_id: str) -> list[str]:
    docs = (
        db.collection(NARRATOR_PERSONA_VERSIONS_COLLECTION)
        .where(filter=firestore.FieldFilter("persona_id", "==", persona_id))
        .stream()
    )
    return [d.id for d in docs]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display-name", default=None, help="完全一致で検索するdisplay_name")
    parser.add_argument("--owner-uid", default=None, help="完全一致で検索するowner_uid")
    parser.add_argument("--execute", action="store_true", help="指定しない限りドライラン(削除しない)")
    args = parser.parse_args()

    if not args.display_name and not args.owner_uid:
        print("[delete_narrator_persona] --display-name か --owner-uid の少なくとも一方を指定してください。")
        return 1

    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})
    _ensure_firebase_app()
    db = firestore.client()

    matched = _find_matching_personas(db, display_name=args.display_name, owner_uid=args.owner_uid)
    if not matched:
        print("[delete_narrator_persona] 一致するnarrator_personasドキュメントはありませんでした。")
        return 0

    plan: list[tuple[str, list[str]]] = []
    for p in matched:
        version_ids = _find_versions_for_persona(db, p["doc_id"])
        plan.append((p["doc_id"], version_ids))
        print(
            f"[delete_narrator_persona] 対象: narrator_personas/{p['doc_id']} "
            f"(display_name={p.get('display_name')!r}, owner_uid={p.get('owner_uid')!r}, "
            f"owner_display_name={p.get('owner_display_name')!r}, is_builtin={p.get('is_builtin')})"
        )
        for vid in version_ids:
            print(f"[delete_narrator_persona]   -> narrator_persona_versions/{vid}")

    if not args.execute:
        print("[delete_narrator_persona] ドライランのため削除は行っていません。実行するには --execute を付けてください。")
        return 0

    for persona_doc_id, version_ids in plan:
        for vid in version_ids:
            db.collection(NARRATOR_PERSONA_VERSIONS_COLLECTION).document(vid).delete()
            print(f"[delete_narrator_persona] 削除完了: narrator_persona_versions/{vid}")
        db.collection(NARRATOR_PERSONAS_COLLECTION).document(persona_doc_id).delete()
        print(f"[delete_narrator_persona] 削除完了: narrator_personas/{persona_doc_id}")

    print(f"[delete_narrator_persona] 完了: persona {len(plan)}件、version {sum(len(v) for _, v in plan)}件を削除しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

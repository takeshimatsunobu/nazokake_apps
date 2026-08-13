"""
tools/migrate_phase3_narrator_persona_link.py
================================================
使い捨てマイグレーションスクリプト。docs/persona_feature_plan_v3.md Phase 3用。

Alembicマイグレーション(7cef352f0e11_add_narrator_persona_link_fields.py)で
追加した narrator_persona_id / narrator_persona_version_id / narrator_persona_name /
data_origin の4列へ、既存データを埋め戻す(§3.5「移行時の埋め方」)。

対象2データソース(計127件、互いに排他的な形状のため重複しない):
  1. persona JSONが {"persona_id":.., "temperature":..} 形(10件)
     → そのpersona_idを直接採用。
  2. data/phase3_rescue/narrator_persona_occupation_name_rescue.json
     (tools/migrate_phase2.pyがPhase2で退避した117件)
     → matched_persona_idを採用。

それ以外の行は触らない(Alembicのserver_defaultで既に"No_Data"/"no_data"が
入っている)。narrator_persona_version_idは、実体となるバージョニング基盤自体が
Phase4で新設される予定のため、本スクリプトでは対象127件についても"No_Data"の
ままとする(意図的に更新しない)。

前提: 実行前に nazokake_local.db の物理バックアップ(zip)を別途取得済みであること。

使い方:
    uv run python tools/migrate_phase3_narrator_persona_link.py
    uv run python tools/migrate_phase3_narrator_persona_link.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "packages" / "shared_core"))

from nazokake_core.database import _resolve_repo_root_default_db_path  # noqa: E402
from nazokake_core.personas import PERSONAS  # noqa: E402

RESCUE_INPUT_PATH = (
    BASE_DIR / "data" / "phase3_rescue" / "narrator_persona_occupation_name_rescue.json"
)


def _resolve_db_path() -> Path:
    return Path(
        os.environ.get("NAZOKAKE_DB_PATH") or _resolve_repo_root_default_db_path()
    ).resolve()


def find_persona_id_temperature_rows(con: sqlite3.Connection) -> list[tuple[str, int]]:
    """persona JSONが{"persona_id":.., "temperature":..}形の行(想定10件)を
    doc_id/persona_idの組で返す。"""
    cur = con.cursor()
    cur.execute("SELECT doc_id, persona FROM nazokake_items WHERE persona IS NOT NULL")
    matches: list[tuple[str, int]] = []
    for doc_id, persona_raw in cur.fetchall():
        if persona_raw in (None, "null"):
            continue
        try:
            p = json.loads(persona_raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(p, dict):
            continue
        if set(p.keys()) == {"persona_id", "temperature"}:
            pid = p.get("persona_id")
            if isinstance(pid, int) and pid in PERSONAS:
                matches.append((doc_id, pid))
    return matches


def load_rescued_117() -> list[tuple[str, int]]:
    """Phase2の救出ファイルからdoc_id/matched_persona_idの組を読み込む。"""
    payload = json.loads(RESCUE_INPUT_PATH.read_text(encoding="utf-8"))
    records = payload["records"]
    return [(r["doc_id"], r["matched_persona_id"]) for r in records]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase3移行: 127件(10件+117件)へnarrator_persona_id等を埋め戻す"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="書き込みを行わずログのみ出力する"
    )
    args = parser.parse_args()

    db_path = _resolve_db_path()
    print(f"[migrate_phase3] 対象DB: {db_path}")
    if args.dry_run:
        print("[migrate_phase3] --dry-run: 書き込みは行いません")

    if not RESCUE_INPUT_PATH.exists():
        print(f"[migrate_phase3] ❌ 救出ファイルが見つかりません: {RESCUE_INPUT_PATH}")
        print("[migrate_phase3] tools/migrate_phase2.py を先に実行してください。")
        return 1

    con = sqlite3.connect(str(db_path))
    try:
        source_10 = find_persona_id_temperature_rows(con)
        source_117 = load_rescued_117()

        print(f"[migrate_phase3] persona_id/temperature形(想定10件): {len(source_10)}件")
        print(f"[migrate_phase3] Phase2救出117件ファイル読み込み: {len(source_117)}件")

        # 重複チェック(2つのデータソースは形状が排他のはずだが、念のため確認する)。
        doc_ids_10 = {doc_id for doc_id, _ in source_10}
        doc_ids_117 = {doc_id for doc_id, _ in source_117}
        overlap = doc_ids_10 & doc_ids_117
        if overlap:
            print(
                f"[migrate_phase3] ⚠️ 2つのデータソースでdoc_idが重複しています"
                f"({len(overlap)}件)。117件側を優先して1回のみ更新します。"
            )

        combined: dict[str, int] = {}
        for doc_id, pid in source_10:
            combined[doc_id] = pid
        for doc_id, pid in source_117:
            combined[doc_id] = pid  # 117件側を優先(重複時)

        cur = con.cursor()
        updated_from_10 = 0
        updated_from_117 = 0
        not_found = 0

        for doc_id, pid in combined.items():
            persona_name = PERSONAS[pid]["name"]
            if not args.dry_run:
                cur.execute(
                    """
                    UPDATE nazokake_items
                    SET narrator_persona_id = ?, narrator_persona_name = ?, data_origin = 'builtin'
                    WHERE doc_id = ?
                    """,
                    (str(pid), persona_name, doc_id),
                )
                affected = cur.rowcount
            else:
                cur.execute("SELECT 1 FROM nazokake_items WHERE doc_id = ?", (doc_id,))
                affected = 1 if cur.fetchone() else 0

            if affected == 0:
                not_found += 1
                continue
            if doc_id in doc_ids_117:
                updated_from_117 += 1
            else:
                updated_from_10 += 1

        if not args.dry_run:
            con.commit()

        print("[migrate_phase3] 移行結果:")
        print(f"    updated_from_persona_id_temperature(10件由来): {updated_from_10}")
        print(f"    updated_from_rescued_117(117件由来): {updated_from_117}")
        print(f"    total_updated: {updated_from_10 + updated_from_117}")
        print(f"    not_found_in_db(doc_id不在): {not_found}")

        if not args.dry_run:
            cur.execute(
                "SELECT count(*) FROM nazokake_items WHERE narrator_persona_id != 'No_Data'"
            )
            total_non_default = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM nazokake_items WHERE data_origin = 'builtin'"
            )
            total_builtin = cur.fetchone()[0]
            print("[migrate_phase3] 完了条件検証:")
            print(f"    narrator_persona_idが'No_Data'以外の行数: {total_non_default}")
            print(f"    data_origin='builtin'の行数: {total_builtin}")
    finally:
        con.close()

    print("[migrate_phase3] 完了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

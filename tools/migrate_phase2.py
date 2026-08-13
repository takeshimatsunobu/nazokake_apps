"""
tools/migrate_phase2.py
=========================
使い捨てマイグレーションスクリプト。docs/persona_feature_plan_v3.md Phase 2用。

実行内容(この順序で実行する):
  1. nazokake_items.persona JSON内のoccupation_nameが PERSONAS[1..10] のnameと
     完全一致する行(想定117件)を、Phase3で使う救出用JSONへ書き出す
     (読み取りのみ。personaカラム自体はこの段階では一切変更しない)。
  2. nazokake_items.scores JSONから S_persona / S_aufheben の2キーを削除し、
     s_totalを残りの軸の平均 × 5.0 で再計算する(§4.2)。

前提: 実行前に nazokake_local.db の物理バックアップ(zip)を別途取得済みであること
(このスクリプト自体はバックアップを取らない)。

冪等性: 既に2キーが存在しない行はscoresの中身を書き換えないが、s_totalは
既存値と異なる場合のみ更新する(2回目以降の実行では通常差分が出ない)。

使い方:
    uv run python tools/migrate_phase2.py              # 実際に書き込む
    uv run python tools/migrate_phase2.py --dry-run    # 書き込まずログのみ確認
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "packages" / "shared_core"))

from nazokake_core.database import _resolve_repo_root_default_db_path  # noqa: E402
from nazokake_core.personas import PERSONAS  # noqa: E402

AXES_TO_REMOVE = ("S_persona", "S_aufheben")

RESCUE_OUTPUT_PATH = (
    BASE_DIR / "data" / "phase3_rescue" / "narrator_persona_occupation_name_rescue.json"
)


def _resolve_db_path() -> Path:
    """database.pyと同一のルール(環境変数NAZOKAKE_DB_PATH優先、未設定時はリポジトリ
    ルート直下の絶対パス)でDBパスを解決する。"""
    return Path(
        os.environ.get("NAZOKAKE_DB_PATH") or _resolve_repo_root_default_db_path()
    ).resolve()


def _name_to_persona_id() -> dict[str, int]:
    return {v["name"]: k for k, v in PERSONAS.items()}


def rescue_117(con: sqlite3.Connection) -> list[dict]:
    """persona.occupation_nameがPERSONAS[1..10]のnameと完全一致する行を救出する。

    読み取りのみ。personaカラムはこの関数では一切書き換えない
    (§2.3: 削除前に必ず実施する救出フェーズ)。
    """
    name_to_id = _name_to_persona_id()
    cur = con.cursor()
    cur.execute("SELECT doc_id, persona FROM nazokake_items WHERE persona IS NOT NULL")
    rescued: list[dict] = []
    for doc_id, persona_raw in cur.fetchall():
        if persona_raw in (None, "null"):
            continue
        try:
            p = json.loads(persona_raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(p, dict):
            continue
        occupation_name = p.get("occupation_name")
        if occupation_name in name_to_id:
            rescued.append(
                {
                    "doc_id": doc_id,
                    "matched_persona_id": name_to_id[occupation_name],
                    "occupation_name": occupation_name,
                    "original_persona": p,
                }
            )
    return rescued


def migrate_scores(con: sqlite3.Connection, *, dry_run: bool) -> dict:
    """全件のscoresからS_persona/S_aufhebenを削除し、s_totalを再計算する(§4.2)。"""
    cur = con.cursor()
    cur.execute("SELECT doc_id, scores, s_total FROM nazokake_items")
    all_rows = cur.fetchall()

    stats = {
        "total_rows": len(all_rows),
        "skipped_null_scores": 0,
        "skipped_invalid_or_non_numeric": 0,
        "keys_removed_count": 0,
        "s_total_recalculated_count": 0,
        "s_total_unchanged_count": 0,
        "rows_updated": 0,
    }

    updates: list[tuple[str, float, str]] = []

    for doc_id, scores_raw, old_s_total in all_rows:
        if scores_raw in (None, "null"):
            stats["skipped_null_scores"] += 1
            continue
        try:
            scores = json.loads(scores_raw)
        except (TypeError, json.JSONDecodeError):
            stats["skipped_invalid_or_non_numeric"] += 1
            continue
        if not isinstance(scores, dict) or not scores:
            stats["skipped_invalid_or_non_numeric"] += 1
            continue
        if not all(isinstance(v, (int, float)) for v in scores.values()):
            # 過去世代の非フラットな不正形状(実測1件: {"scores": {...}, "status": ...}
            # のようなネスト構造)。安全側でスキップし、手動確認へ回す。
            stats["skipped_invalid_or_non_numeric"] += 1
            continue

        had_extra = any(k in scores for k in AXES_TO_REMOVE)
        for k in AXES_TO_REMOVE:
            scores.pop(k, None)
        if had_extra:
            stats["keys_removed_count"] += 1

        if not scores:
            # 全キー削除後に空になった(想定外)行は安全側でスキップする。
            stats["skipped_invalid_or_non_numeric"] += 1
            continue

        new_s_total = round(sum(scores.values()) / len(scores) * 5.0, 4)
        if new_s_total != old_s_total:
            stats["s_total_recalculated_count"] += 1
        else:
            stats["s_total_unchanged_count"] += 1

        updates.append((json.dumps(scores, ensure_ascii=False), new_s_total, doc_id))

    if not dry_run:
        cur.executemany(
            "UPDATE nazokake_items SET scores = ?, s_total = ? WHERE doc_id = ?",
            updates,
        )
        con.commit()

    stats["rows_updated"] = len(updates)
    return stats


def verify(con: sqlite3.Connection) -> dict:
    """完了条件の機械的検証: 全件のscoresに2キーが残っていないこと。"""
    cur = con.cursor()
    cur.execute("SELECT scores FROM nazokake_items WHERE scores IS NOT NULL")
    remaining = 0
    for (scores_raw,) in cur.fetchall():
        if scores_raw in (None, "null"):
            continue
        try:
            scores = json.loads(scores_raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(scores, dict) and any(k in scores for k in AXES_TO_REMOVE):
            remaining += 1
    return {"rows_still_containing_removed_axes": remaining}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase2移行: 117件救出 + scoresの2軸削除 + s_total再計算"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="書き込みを行わずログのみ出力する"
    )
    args = parser.parse_args()

    db_path = _resolve_db_path()
    print(f"[migrate_phase2] 対象DB: {db_path}")
    if args.dry_run:
        print("[migrate_phase2] --dry-run: 書き込みは行いません")

    con = sqlite3.connect(str(db_path))
    try:
        # --- Step 1: 117件の救出(読み取りのみ) ---
        rescued = rescue_117(con)
        rescue_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "persona_feature_plan_v3.md Phase2, tools/migrate_phase2.py",
            "description": (
                "nazokake_items.persona.occupation_name が PERSONAS[1..10] の "
                "nameと完全一致した行の救出データ。Phase3でnarrator_persona_idへの"
                "紐付けに使う想定。"
            ),
            "count": len(rescued),
            "records": rescued,
        }
        if not args.dry_run:
            RESCUE_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            RESCUE_OUTPUT_PATH.write_text(
                json.dumps(rescue_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        print(f"[migrate_phase2] 117件救出: {len(rescued)}件 -> {RESCUE_OUTPUT_PATH}")
        if len(rescued) != 117:
            print(
                f"[migrate_phase2] ⚠️ 計画書の想定件数(117件)と一致しません"
                f"(実際: {len(rescued)}件)。後続の処理は継続します。"
            )

        # --- Step 2: scoresから2キー削除 + s_total再計算 ---
        stats = migrate_scores(con, dry_run=args.dry_run)
        print("[migrate_phase2] scores移行結果:")
        for k, v in stats.items():
            print(f"    {k}: {v}")

        # --- Step 3: 完了条件の機械的検証 ---
        if not args.dry_run:
            verify_stats = verify(con)
            print("[migrate_phase2] 完了条件検証:")
            for k, v in verify_stats.items():
                print(f"    {k}: {v}")
    finally:
        con.close()

    print("[migrate_phase2] 完了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

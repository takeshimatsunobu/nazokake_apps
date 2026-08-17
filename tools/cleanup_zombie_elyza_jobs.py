"""
tools/cleanup_zombie_elyza_jobs.py
=====================================
本番調査(2026-08-18): ELYZAオンデマンドワーカーが「常に8秒ACKタイムアウトで
Gemini Flash代打になる」障害の直接原因のひとつだった、Firestore上に
elyza_job_status="pending"のまま永久に取り残された「ゾンビジョブ」の
一回性クリーンアップCLI。

【根本原因】packages/shared_core/nazokake_core/firestore_sync.py::
_build_push_payload() のバグにより、8秒ACKタイムアウト確定時にCloud Run自身が
書く"pending"→"cancelled"の更新がFirestoreへ反映されず、elyza_job_statusが
"pending"のまま取り残されていた(このスクリプトと同時に修正済み、
firestore_sync.pyの_ELYZA_JOB_STATUS_UNCLAIMED関連コメント参照)。

放置すると、workers/ondemand_elyza_worker.py::_find_claimable_doc_idsの
pendingクエリがこれらのゾンビジョブを繰り返し拾い続け、ワーカーの処理枠
(CLAIM_BATCH_SIZE)を既に代打確定済みの無駄なジョブで消費し、新規ジョブが
8秒ACK窓に間に合わなくなる一因となる。

【対象の判定】elyza_job_status=="pending" かつ、以下いずれかを満たすもの:
  - status(Gemini側)が終端状態("all_completed"/"error")に達している
    (=このドキュメント全体の生成は既に決着しており、ELYZAジョブだけが
    論理的にはとっくに終わっているはずなのにpendingのまま)
  - created_atが_STALE_HOURS時間より過去(生きているジョブなら8秒ACK+
    45秒完了待ちでとっくに決着しているはずの時間を大きく超えている)

【安全策】既定はドライラン(対象件数と内容を表示するのみ、書き込まない)。
実際に更新するには --execute を明示的に渡す必要がある。書き込みは
elyza_job_status を "cancelled" へ更新するのみ(workers/側の
_ELYZA_JOB_SCOPED_FIELDS/_is_claimable()の許可リストに従い、"cancelled"は
claim対象から構造的に除外される、_is_claimable()参照)。他のフィールド
(result_llmjp等)には一切触れない。

使い方:
    uv run python tools/cleanup_zombie_elyza_jobs.py
    uv run python tools/cleanup_zombie_elyza_jobs.py --execute
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "packages" / "shared_core"))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import firebase_admin  # noqa: E402
from firebase_admin import firestore  # noqa: E402

from nazokake_core.firestore_sync import _ensure_firebase_app, _resolve_collection  # noqa: E402

_TERMINAL_GEMINI_STATUSES = {"all_completed", "error"}
_STALE_HOURS = 1.0


def _is_zombie(data: dict) -> bool:
    if data.get("elyza_job_status") != "pending":
        return False
    if data.get("status") in _TERMINAL_GEMINI_STATUSES:
        return True
    created_at = data.get("created_at")
    if not created_at:
        return False
    try:
        created_dt = datetime.datetime.fromisoformat(created_at)
    except ValueError:
        return False
    if created_dt.tzinfo is None:
        created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
    age_hours = (datetime.datetime.now(datetime.timezone.utc) - created_dt).total_seconds() / 3600
    return age_hours > _STALE_HOURS


def _find_zombie_jobs(db, collection: str) -> list[dict]:
    docs = db.collection(collection).where(
        filter=firestore.FieldFilter("elyza_job_status", "==", "pending")
    ).stream()
    zombies = []
    for doc in docs:
        data = doc.to_dict() or {}
        if _is_zombie(data):
            zombies.append({"doc_id": doc.id, **data})
    return zombies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="指定しない限りドライラン(更新しない)")
    args = parser.parse_args()

    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})
    _ensure_firebase_app()
    db = firestore.client()
    collection = _resolve_collection()

    zombies = _find_zombie_jobs(db, collection)
    if not zombies:
        print("[cleanup_zombie_elyza_jobs] 対象のゾンビジョブはありませんでした。")
        return 0

    for z in zombies:
        print(
            f"[cleanup_zombie_elyza_jobs] 対象: {collection}/{z['doc_id']} "
            f"(status={z.get('status')!r}, llmjp_status={z.get('llmjp_status')!r}, "
            f"created_at={z.get('created_at')!r})"
        )

    if not args.execute:
        print(
            f"[cleanup_zombie_elyza_jobs] ドライランのため更新は行っていません"
            f"({len(zombies)}件が対象)。実行するには --execute を付けてください。"
        )
        return 0

    updated = 0
    for z in zombies:
        db.collection(collection).document(z["doc_id"]).update(
            {"elyza_job_status": "cancelled"}
        )
        print(f"[cleanup_zombie_elyza_jobs] 更新完了: {collection}/{z['doc_id']} -> cancelled")
        updated += 1

    print(f"[cleanup_zombie_elyza_jobs] 完了: {updated}件をcancelledへ更新しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

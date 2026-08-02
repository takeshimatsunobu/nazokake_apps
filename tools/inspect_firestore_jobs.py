"""
tools/inspect_firestore_jobs.py
==================================
Firestore の nazokake_items コレクションから、直近のなぞかけ生成ジョブの状態
(status / elyza_job_status 等)を読み取り専用で調査するための公式CLIツール
(instructions/301)。

【絶対制約】AgentがFirestoreのジョブ状態を調査する際は、必ず本ツールを経由すること。
環境の壁によるクラッシュを防ぐため、Agentが動的にFirestore接続スクリプトを自作する
ことは固く禁ずる。

【背景】過去の調査でAgentがFirestore接続スクリプトをその場で自作した結果、認証情報
のロード機構(GCP_PROJECT_ID未設定時のADCフォールバック、firebase_adminアプリの
多重初期化ガード等の既存の作法)を踏まえずに実装してしまい、認証エラーによる
クラッシュが多発した。本ツールはバックエンドが既に確立している
nazokake_core.firestore_sync._ensure_firebase_app() / _resolve_collection() を
無改変で再利用することで、この種のクラッシュを構造的に防ぐ。

【読み取り専用】本ツールはFirestoreへの書き込み・削除を一切行わない。

使い方:
    uv run python tools/inspect_firestore_jobs.py                  # 直近20件を一覧表示
    uv run python tools/inspect_firestore_jobs.py --limit 50        # 直近50件を一覧表示
    uv run python tools/inspect_firestore_jobs.py --pending-only    # pending滞留疑いのみ表示
    uv run python tools/inspect_firestore_jobs.py --doc-id <doc_id> # 特定の1件のみ調査
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from firebase_admin import firestore  # noqa: E402

from nazokake_core.firestore_sync import (  # noqa: E402
    _ensure_firebase_app,
    _resolve_collection,
)

DEFAULT_LIMIT = 20

# 調査対象として報告するフィールド(instructions/250のELYZAオンデマンドジョブ
# キュー・スコープに合わせる。書き込み対象フィールドは一切変更しない)。
_REPORT_FIELDS = (
    "doc_id",
    "odai",
    "status",
    "elyza_job_status",
    "elyza_job_locked_at",
    "elyza_job_retry_count",
    "created_at",
    "updated_at",
)


def _is_pending(job: dict[str, Any]) -> bool:
    """status または elyza_job_status のいずれかが"pending"のまま滞留していないか。"""
    return job.get("status") == "pending" or job.get("elyza_job_status") == "pending"


def fetch_recent_jobs(limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """直近更新順(updated_at降順)でジョブを読み取る。

    created_atではなくupdated_atを並び替え基準とする。ORM側の設計上
    (packages/shared_core/nazokake_core/database.py:upsert_item())、
    updated_atはあらゆるupsertで必ずサーバー側から設定されるのに対し、
    created_atは部分行(キュー投入直後でまだ他フィールドが埋まっていない行)では
    欠損しうる。Firestoreのorder_byは対象フィールドを持たないドキュメントを結果から
    除外するため、created_atを基準にすると調査対象のpending滞留行そのものを
    取りこぼす恐れがある。
    """
    _ensure_firebase_app()
    db = firestore.client()
    collection = _resolve_collection()

    query = (
        db.collection(collection)
        .order_by("updated_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    jobs: list[dict[str, Any]] = []
    for doc in query.stream():
        data = doc.to_dict() or {}
        data.setdefault("doc_id", doc.id)
        jobs.append(data)
    return jobs


def fetch_job_by_id(doc_id: str) -> dict[str, Any] | None:
    """特定のdoc_idを1件だけ読み取る。存在しない場合はNoneを返す。"""
    _ensure_firebase_app()
    db = firestore.client()
    collection = _resolve_collection()

    snapshot = db.collection(collection).document(doc_id).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    data.setdefault("doc_id", snapshot.id)
    return data


def _format_job(job: dict[str, Any]) -> str:
    return "\n".join(f"    {field}: {job.get(field)!r}" for field in _REPORT_FIELDS)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Firestore nazokake_items コレクションのジョブ状態を読み取り専用で"
            "調査する公式ツール(instructions/301)。"
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"調査する直近件数(updated_at降順、既定: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--pending-only",
        action="store_true",
        help="status または elyza_job_status が pending の行のみ表示する",
    )
    parser.add_argument(
        "--doc-id",
        type=str,
        default=None,
        help="特定のdoc_idを1件だけ調査する(--limit/--pending-onlyとは併用不可)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if args.doc_id:
        job = fetch_job_by_id(args.doc_id)
        if job is None:
            print(f"🚨 doc_id={args.doc_id!r} は見つかりませんでした。")
            return 1
        print(f"=== doc_id={args.doc_id} ===")
        print(_format_job(job))
        return 0

    jobs = fetch_recent_jobs(args.limit)
    if args.pending_only:
        jobs = [job for job in jobs if _is_pending(job)]

    if not jobs:
        print("該当するジョブはありませんでした。")
        return 0

    pending_count = sum(1 for job in jobs if _is_pending(job))
    print(f"=== 直近{len(jobs)}件中、pending(滞留疑い) {pending_count}件 ===\n")
    for job in jobs:
        marker = "⚠️  PENDING" if _is_pending(job) else "  ok      "
        print(f"[{marker}] doc_id={job.get('doc_id')}")
        print(_format_job(job))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

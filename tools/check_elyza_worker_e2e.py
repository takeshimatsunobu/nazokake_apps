"""
tools/check_elyza_worker_e2e.py
===================================
本番調査(2026-08-18)の改善タスク: ELYZAオンデマンドワーカー(workers/
ondemand_elyza_worker.py)単体で、Firestore接続・ジョブの模擬受信・claim・
Ollama推論・評価・結果書き戻しまでが一気通貫で動作するかを確認する検証CLI。

本物のnazokake_itemsコレクションは一切汚さない。既定でテスト専用コレクション
(--collection、既定値 "nazokake_items_e2e_test")へ模擬ジョブを直接書き込み、
workers/ondemand_elyza_worker.py が実際に使っている関数(_claim_job_sync/
_process_job等)をそのまま呼び出して検証する(ロジックの二重実装を避ける)。
検証後は既定で模擬ジョブを削除する(--keep で残せる)。

前提: ローカルOllama(既定 http://localhost:11434、モデル既定 elyza:8b)が
起動していること。Firestore接続はワーカー本体と同じ nazokakeapp-137e5
プロジェクトを使う。

使い方:
    uv run python tools/check_elyza_worker_e2e.py
    uv run python tools/check_elyza_worker_e2e.py --keep
    uv run python tools/check_elyza_worker_e2e.py --collection nazokake_items_e2e_test
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import sys
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "apps" / "evaluator" / "backend"
for _path in (BASE_DIR, BACKEND_DIR, BASE_DIR / "packages" / "shared_core"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# workers/ondemand_elyza_worker.py 自身の規約(.env読み込み・project_id明示init)
# より前に、このスクリプト自身が使うコレクション名を環境変数で確定させる
# (FIRESTORE_SYNC_COLLECTIONはnazokake_core.firestore_sync._resolve_collection()
# が読む唯一の切り替え口)。
import os  # noqa: E402


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--collection",
        default="nazokake_items_e2e_test",
        help="検証専用コレクション名(本番nazokake_itemsは既定では絶対に使わない)",
    )
    p.add_argument("--keep", action="store_true", help="検証後も模擬ジョブを削除せず残す")
    p.add_argument("--odai", default="健康チェック", help="模擬ジョブのお題")
    p.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="Ollama生成+評価の完了を待つ最大秒数(既定90秒)",
    )
    return p


def _step(n: int, label: str) -> None:
    print(f"\n[{n}/5] {label}")


async def main_async(args: argparse.Namespace) -> int:
    os.environ["FIRESTORE_SYNC_COLLECTION"] = args.collection

    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")

    import firebase_admin
    from firebase_admin import firestore

    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})

    from nazokake_core.database import ensure_db_ready
    from nazokake_core.firestore_sync import _ensure_firebase_app, _resolve_collection

    import workers.ondemand_elyza_worker as worker  # noqa: E402

    _ensure_firebase_app()
    db = firestore.client()
    collection = _resolve_collection()
    assert collection == args.collection, (
        f"想定外のコレクションに接続しようとしています: {collection}"
        "(FIRESTORE_SYNC_COLLECTIONの反映に失敗している可能性があります)"
    )

    doc_id = f"e2e-{uuid.uuid4().hex[:12]}"
    print(f"=== ELYZAワーカー疎通検証 (collection={collection}, doc_id={doc_id}) ===")

    _step(1, "Firestore接続確認 + 模擬pendingジョブの投入")
    doc_ref = db.collection(collection).document(doc_id)
    doc_ref.set(
        {
            "doc_id": doc_id,
            "odai": args.odai,
            "elyza_job_status": "pending",
            "elyza_job_locked_at": None,
            "elyza_job_retry_count": 0,
            "persona": {"persona_id": "1", "temperature": 0.6},
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    )
    print(f"    ✅ Firestore接続OK。模擬ジョブを投入しました: {collection}/{doc_id}")

    try:
        _step(2, "Ollama疎通診断")
        worker._check_ollama_reachable()

        _step(3, "ジョブclaim(_claim_job_sync)")
        job = await asyncio.to_thread(worker._claim_job_sync, db, collection, doc_id)
        if job is None:
            print("    🚨 claimに失敗しました(pending判定漏れの可能性)。検証を中止します。")
            return 1
        print(f"    ✅ claim成功: odai={job['odai']!r}")

        _step(4, f"Ollama推論+評価+結果書き戻し(_process_job、最大{args.timeout:.0f}秒待機)")
        ensure_db_ready()
        try:
            await asyncio.wait_for(
                worker._process_job(db, collection, job), timeout=args.timeout
            )
        except asyncio.TimeoutError:
            print(f"    🚨 {args.timeout:.0f}秒以内に完了しませんでした。検証を中止します。")
            return 1

        _step(5, "結果検証")
        final = doc_ref.get().to_dict() or {}
        elyza_status = final.get("elyza_job_status")
        llmjp_status = final.get("llmjp_status")
        print(f"    elyza_job_status={elyza_status!r} / llmjp_status={llmjp_status!r}")
        if elyza_status == "completed" and llmjp_status == "completed":
            print("\n✅ 一気通貫での疎通に成功しました(Firestore→claim→Ollama→評価→書き戻し)。")
            return 0
        print(
            "\n⚠️ ジョブは処理されましたが、期待した完了状態になりませんでした"
            f"(elyza_job_status={elyza_status!r}, llmjp_status={llmjp_status!r})。"
            "Ollama応答の品質やGemini評価側の問題の可能性があります。"
        )
        return 1
    finally:
        if args.keep:
            print(f"\n[--keep指定] 模擬ジョブを残します: {collection}/{doc_id}")
        else:
            doc_ref.delete()
            print(f"\n🧹 模擬ジョブを削除しました: {collection}/{doc_id}")


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())

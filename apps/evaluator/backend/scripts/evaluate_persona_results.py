"""nazokake_results (apps/persona_router 由来) の事後評価バッチ（Phase4）。

apps/persona_router/api/routers/generate.py は生成と同時に評価を行わない
(同期APIのレイテンシを増やさないための設計判断)。そのため nazokake_results の
各ドキュメントは書き込まれた時点では scores/s_total を持たない。このスクリプトは
未評価のドキュメントを走査し、apps/evaluator/backend/services/evaluation.py の
13軸ルーブリック(run_evaluation)で採点し、結果を同ドキュメントへ書き戻す。

書き戻すフィールド: scores, s_total, axis_comments, overall, evaluated_at (ISO8601)。
一度評価済みのドキュメント(evaluated_atを持つもの)は再評価しない(冪等・低コスト)。

実行: (apps/evaluator/backend で) uv run python scripts/evaluate_persona_results.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import firebase_admin
from firebase_admin import firestore

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: S110 (reconfigure非対応環境向けの意図的なフォールバック)
    pass

# services.evaluation を絶対importできるよう、apps/evaluator/backend をsys.pathへ追加する
# (このスクリプト自身は apps/evaluator/backend/scripts/ に置かれるため、親を辿る)。
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.evaluation import run_evaluation  # noqa: E402

RESULTS_COLLECTION = "nazokake_results"


def init_db():
    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})
    return firestore.client()


async def main(dry_run: bool = False, limit: int | None = None) -> None:
    db = init_db()

    print(f"🔍 {RESULTS_COLLECTION} の未評価ドキュメントを走査します...")
    targets = []
    for doc in db.collection(RESULTS_COLLECTION).stream():
        item = doc.to_dict() or {}
        if item.get("evaluated_at"):
            continue
        odai = (item.get("odai") or "").strip()
        text = (item.get("nazokake_text") or "").strip()
        if not odai or not text:
            continue
        targets.append((doc.id, odai, text))

    if limit is not None:
        targets = targets[:limit]

    print(f"📊 評価対象: {len(targets)} 件")
    if dry_run:
        print("🧪 [DRY-RUN] 評価は実行せず、対象件数の確認のみで終了します。")
        return

    evaluated = 0
    failed = 0
    for doc_id, odai, text in targets:
        try:
            result = await run_evaluation(odai, text)
        except Exception as e:
            failed += 1
            print(f"⚠️ 評価失敗 (doc_id={doc_id}): {e}")
            continue

        db.collection(RESULTS_COLLECTION).document(doc_id).update(
            {
                "scores": result["scores"],
                "s_total": result["s_total"],
                "axis_comments": result["axis_comments"],
                "overall": result["overall"],
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        evaluated += 1
        if evaluated % 10 == 0:
            print(f"  ... {evaluated}/{len(targets)} 件評価完了")

    print(f"✅ 評価完了: {evaluated} 件成功 / {failed} 件失敗")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="nazokake_results の事後評価バッチ")
    parser.add_argument("--dry-run", action="store_true", help="対象件数の確認のみ行う")
    parser.add_argument("--limit", type=int, default=None, help="評価件数の上限(テスト用)")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run, limit=args.limit))

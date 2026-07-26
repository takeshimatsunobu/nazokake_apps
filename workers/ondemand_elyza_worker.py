"""
workers/ondemand_elyza_worker.py
==================================
instructions/250: クラウド・ローカル連携によるオンデマンドELYZA生成ワーカー。

Cloud Run(本番)にはローカルのOllama/ELYZAへ到達する経路が(本番トンネルが常時
接続されていない限り)無いため、"おまけ"生成を即座に処理できない。本ワーカーは
Firestore経由の非同期メッセージングで、ユーザーのローカルGPUマシン上でELYZA生成・
評価を代行し、結果を書き戻す。

【split-brain回避のスコープ限定(SSoT §8.2 一方向同期原則への名前付き・限定的な例外)】
Cloud Run側は絶対にFirestoreへ直接書き込まない。「pending」の合図はCloud Run自身の
ローカルSQLite(apps/evaluator/backend、POST /generateの通常upsert)に書かれ、
既存の一方向同期(nazokake_core.firestore_sync.sync_once)が自動的にFirestoreへ
伝播させる(新規の書き込み経路を増やさない)。このワーカーだけが、以下の狭い
フィールド集合に限り、Firestoreへ直接書き込む権限を持つ第二の書き手として明示的に
許可される:
    elyza_job_status, elyza_job_locked_at, elyza_job_retry_count,
    llmjp_status, result_llmjp, nazokake_text_llmjp, scores_llmjp,
    s_total_llmjp, overall_llmjp, axis_comments_llmjp
status/eval_status/result/result_gemini/scores/message等のGemini・主系フィールドには
一切触れない。

使い方:
    uv run python workers/ondemand_elyza_worker.py                  # 1周期だけ実行
    uv run python workers/ondemand_elyza_worker.py --loop            # デーモンとして常駐
    uv run python workers/ondemand_elyza_worker.py --loop --interval 30
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import signal
import sys
import time
import traceback
from pathlib import Path
from types import FrameType
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
# apps/evaluator/backend の services.generation / services.evaluation をそのまま
# 再利用するため(generate_via_llmjp / run_evaluationの再実装を避けるため)、
# そのディレクトリをsys.pathへ追加する。
BACKEND_DIR = BASE_DIR / "apps" / "evaluator" / "backend"
for _path in (BASE_DIR, BACKEND_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from dotenv import load_dotenv  # noqa: E402
from firebase_admin import firestore  # noqa: E402

from nazokake_core.database import async_upsert_item, ensure_db_ready  # noqa: E402
from nazokake_core.firestore_sync import (  # noqa: E402
    _ensure_firebase_app,
    _resolve_collection,
)
from services.evaluation import run_evaluation  # noqa: E402
from services.generation import generate_via_llmjp  # noqa: E402

DEFAULT_POLL_INTERVAL_SEC = 20.0
CLAIM_BATCH_SIZE = 5
# ワーカークラッシュ等で"processing"のまま停止した場合のゾンビ回収閾値。
STALE_PROCESSING_TIMEOUT_SEC = 900  # 15分
# mark_sync_failed()のポイズンピル判定(MAX_SYNC_RETRIES)と同じ考え方。
MAX_JOB_RETRIES = 3

_ELYZA_JOB_SCOPED_FIELDS = frozenset(
    {
        "elyza_job_status",
        "elyza_job_locked_at",
        "elyza_job_retry_count",
        "llmjp_status",
        "result_llmjp",
        "nazokake_text_llmjp",
        "scores_llmjp",
        "s_total_llmjp",
        "overall_llmjp",
        "axis_comments_llmjp",
    }
)

_shutdown_requested = False


def _log(message: str) -> None:
    """稼働ログをsys.stdoutへ出力する(tools/scheduler_daemon.pyと同じ規約:
    異常系のトレースバックはsys.stderrへ厳格に分離する)。"""
    print(f"[ondemand_elyza_worker] {message}", file=sys.stdout, flush=True)


def _handle_shutdown_signal(signum: int, frame: FrameType | None) -> None:
    """SIGTERM/SIGINT受信時、直ちに終了せずフラグを立てる(Graceful Shutdown、
    tools/scheduler_daemon.pyと同じパターン)。"""
    global _shutdown_requested
    _log(f"🛑 シグナル{signum}を受信しました。Graceful Shutdownします...")
    _shutdown_requested = True


def _interruptible_sleep(seconds: float) -> None:
    """_shutdown_requestedを1秒間隔でポーリングしながらsleepする
    (tools/scheduler_daemon.pyと同じ理由: PEP 475によりtime.sleep()単体では
    シグナル受信後も最大`seconds`秒待たされてしまうため)。"""
    deadline = time.monotonic() + seconds
    while not _shutdown_requested and time.monotonic() < deadline:
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _compose_text(odai: str, result: dict) -> str:
    """apps/evaluator/backend/api/routers/generate.py::_compose_text と同一ロジック。
    workers/からapps/evaluator/backendの内部ヘルパーを直接importするのは越境
    しすぎるため、この1関数だけ意図的に複製する。
    """
    return f"「{odai}」とかけて、「{result.get('toku', '')}」と解く。\nその心は、{result.get('kokoro', '')}"


def _stale_cutoff_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(seconds=STALE_PROCESSING_TIMEOUT_SEC)
    ).isoformat()


def _find_claimable_doc_ids(db, collection: str) -> list[str]:
    """pending、またはstaleなprocessing(ゾンビ)のdoc_idを取得する(読み取りのみ、
    このクエリ自体はまだ何も書き込まない)。"""
    stale_cutoff = _stale_cutoff_iso()

    pending_docs = (
        db.collection(collection)
        .where("elyza_job_status", "==", "pending")
        .limit(CLAIM_BATCH_SIZE)
        .stream()
    )
    stale_docs = (
        db.collection(collection)
        .where("elyza_job_status", "==", "processing")
        .where("elyza_job_locked_at", "<", stale_cutoff)
        .limit(CLAIM_BATCH_SIZE)
        .stream()
    )
    doc_ids: list[str] = []
    seen: set[str] = set()
    for doc in list(pending_docs) + list(stale_docs):
        if doc.id not in seen:
            seen.add(doc.id)
            doc_ids.append(doc.id)
    return doc_ids


def _claim_job_sync(db, collection: str, doc_id: str) -> dict[str, Any] | None:
    """対象ドキュメントをトランザクションで排他的に"processing"へ遷移させる
    (firestore_sync._push_one_syncと同じread-then-writeのアトミック性)。

    再読込時点でpending/staleの条件を満たさなくなっていた場合(別プロセスに
    先に取られた等)はNoneを返してスキップする。
    """
    doc_ref = db.collection(collection).document(doc_id)
    stale_cutoff = _stale_cutoff_iso()

    @firestore.transactional
    def _txn(transaction) -> dict[str, Any] | None:
        snapshot = doc_ref.get(transaction=transaction)
        if not snapshot.exists:
            return None
        remote = snapshot.to_dict() or {}
        status = remote.get("elyza_job_status")
        locked_at = remote.get("elyza_job_locked_at")
        claimable = status == "pending" or (
            status == "processing"
            and (locked_at is None or locked_at < stale_cutoff)
        )
        if not claimable:
            return None
        transaction.update(
            doc_ref,
            {"elyza_job_status": "processing", "elyza_job_locked_at": _now_iso()},
        )
        return {
            "doc_id": doc_id,
            "odai": remote.get("odai") or "",
            "retry_count": remote.get("elyza_job_retry_count") or 0,
        }

    return _txn(db.transaction())


def _write_scoped_fields_sync(
    db, collection: str, doc_id: str, fields: dict[str, Any]
) -> None:
    """狭いフィールド集合のみをFirestoreへ書き戻す(doc_ref.update、非merge set()は
    使わない)。予期しないキーが紛れ込んでいないか、書き込み直前に防御的に検証する。
    """
    unexpected = set(fields) - _ELYZA_JOB_SCOPED_FIELDS
    if unexpected:
        raise ValueError(
            f"スコープ外のフィールドへの書き込みを検知したため中止します: {unexpected}"
        )
    db.collection(collection).document(doc_id).update(fields)


async def _mark_job_outcome(
    db,
    collection: str,
    doc_id: str,
    odai: str,
    *,
    local_fields: dict[str, Any],
    scoped_fields: dict[str, Any],
) -> None:
    """成功/失敗いずれの結果も、ワーカー自身のローカルSQLite(instructions/250
    Step 3.3)とFirestoreの両方へ書く。ローカルSQLiteはワーカー専用の別ファイルで
    あり、doc_idが未知の場合は新規行としてINSERTされる(odaiはNOT NULL制約のため
    必須)。
    """
    await async_upsert_item({"doc_id": doc_id, "odai": odai, **local_fields})
    await asyncio.to_thread(
        _write_scoped_fields_sync, db, collection, doc_id, scoped_fields
    )


async def _process_job(db, collection: str, job: dict[str, Any]) -> None:
    doc_id = job["doc_id"]
    odai = job["odai"]
    retry_count = job["retry_count"]

    if not odai:
        _log(f"⚠️ [{doc_id}] odaiが空のため生成をスキップし、失敗として扱います。")
        await _mark_failure(db, collection, doc_id, odai, retry_count, "odai is empty")
        return

    try:
        raw_result = await generate_via_llmjp(odai)
        text = _compose_text(odai, raw_result)
        evaluation = await run_evaluation(odai, text)
    except Exception as e:
        _log(f"⚠️ [{doc_id}] ELYZA生成/評価に失敗: {e}")
        traceback.print_exc(file=sys.stderr)
        await _mark_failure(db, collection, doc_id, odai, retry_count, str(e))
        return

    fields = {
        "result_llmjp": raw_result,
        "nazokake_text_llmjp": text,
        "scores_llmjp": evaluation["scores"],
        "s_total_llmjp": evaluation["s_total"],
        "overall_llmjp": evaluation["overall"],
        "axis_comments_llmjp": evaluation["axis_comments"],
        "llmjp_status": "completed",
        "elyza_job_status": "completed",
        "elyza_job_locked_at": None,
        "elyza_job_retry_count": 0,
    }
    await _mark_job_outcome(
        db, collection, doc_id, odai, local_fields=fields, scoped_fields=fields
    )
    _log(f"✅ [{doc_id}] ELYZA生成・評価・Firestore書き戻しが完了しました。")


async def _mark_failure(
    db, collection: str, doc_id: str, odai: str, prior_retry_count: int, error_message: str
) -> None:
    """指数バックオフ等の複雑な再試行は行わず、次のポーリング周期で"pending"扱いに
    戻すだけの単純な再試行とする(instructions/250の対象は低頻度のオンデマンド
    ジョブであり、mlops_trigger.pyのような高頻度パイプラインの再試行制御は過剰)。
    MAX_JOB_RETRIES到達時のみ、mark_sync_failed()と同じ考え方でdead_letterへ
    ポイズンピル隔離する(無限リトライループを防ぐ)。
    """
    next_retry_count = prior_retry_count + 1
    terminal = next_retry_count >= MAX_JOB_RETRIES
    next_status = "dead_letter" if terminal else "pending"

    fields: dict[str, Any] = {
        "elyza_job_status": next_status,
        "elyza_job_locked_at": None,
        "elyza_job_retry_count": next_retry_count,
    }
    if terminal:
        fields["llmjp_status"] = "failed"
        _log(
            f"📮 [{doc_id}] {MAX_JOB_RETRIES}回失敗したため dead_letter へ隔離しました: "
            f"{error_message}"
        )

    await _mark_job_outcome(
        db, collection, doc_id, odai, local_fields=fields, scoped_fields=fields
    )


async def run_once() -> int:
    """1周期分: claim可能なジョブを列挙し、1件ずつ順番に処理する。戻り値は処理件数。

    同時に複数ジョブを並行処理しない(generate_via_llmjp内部の_OLLAMA_SEMAPHOREが
    どのみち同時1リクエストへ制限するため、ここで並行化する意味がない)。
    """
    _ensure_firebase_app()
    db = firestore.client()
    collection = _resolve_collection()

    doc_ids = await asyncio.to_thread(_find_claimable_doc_ids, db, collection)
    processed = 0
    for doc_id in doc_ids:
        job = await asyncio.to_thread(_claim_job_sync, db, collection, doc_id)
        if job is None:
            continue  # 既に他の実行に取られていた、または条件を満たさなくなっていた
        _log(f"🎯 [{doc_id}] ジョブをclaimしました(odai='{job['odai']}')。")
        await _process_job(db, collection, job)
        processed += 1
    return processed


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="On-demand ELYZA generation worker (Firestore job queue, instructions/250)"
    )
    p.add_argument(
        "--loop", action="store_true", help="1周期で終了せず、intervalごとに繰り返し実行する"
    )
    p.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SEC,
        help="--loop時のポーリング間隔(秒)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    load_dotenv()
    ensure_db_ready()

    if not args.loop:
        processed = asyncio.run(run_once())
        _log(f"1周期完了({processed}件処理)。")
        return 0

    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    _log(f"デーモンとして起動しました(ポーリング間隔: {args.interval}秒)。")
    while not _shutdown_requested:
        try:
            processed = asyncio.run(run_once())
            if processed:
                _log(f"{processed}件処理しました。")
        except Exception:
            # 1周期の失敗でデーモン自体を落とさない(tools/scheduler_daemon.pyと同じ規約)。
            traceback.print_exc(file=sys.stderr)
        _interruptible_sleep(args.interval)
    _log("Graceful Shutdown完了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

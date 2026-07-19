"""
nazokake_core/database.py
==========================
Local-First アーキテクチャにおける「絶対的な正(Local SSoT)」であるローカルSQLite
データベースへのアクセス基盤。NazokakeItem(Pydantic)に対応するテーブルモデル、
非同期エンジン/セッション管理、および排他制御を伴うキュー操作のDAO関数を提供する。

複数ワーカー(プロセス)からの同時アクセス時のSQLITE_BUSYを二段構えで防ぐ:
1. コネクション確立ごとに PRAGMA journal_mode=WAL / synchronous=NORMAL / busy_timeout を
   強制し、SQLite自体の読み書き並行性とロック競合時の再試行を確保する(プロセス間)。
2. プロセス内の全DB操作は単一の Serialized Writer タスクへ集約し、直列(1件ずつ)に
   実行する(プロセス内)。apps/batch_factory 側の呼び出し元(main.py 等)は同期コードの
   ため、`sync_*` 関数群が Serialized Writer のキューへタスクをpushする唯一の
   インターフェースとして機能する(直接DBへ書き込むことはない)。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import threading
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, TypeVar

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    Integer,
    String,
    Text,
    case,
    event,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

DEFAULT_DB_PATH = "nazokake_local.db"

# ポイズンピル判定の閾値: mark_sync_failed()がこの回数に達したらsync_status="fatal"へ
# 隔離し、get_pending_sync_batch()の対象から外す(無限リトライ防止)。
MAX_SYNC_RETRIES = 3

T = TypeVar("T")


def _resolve_db_url() -> str:
    """環境変数 NAZOKAKE_DB_PATH(未設定時は DEFAULT_DB_PATH)からaiosqlite用の接続URLを組み立てる。"""
    db_path = os.environ.get("NAZOKAKE_DB_PATH", DEFAULT_DB_PATH)
    return f"sqlite+aiosqlite:///{db_path}"


# NullPool: 実際の接続はすべてSerialized Writerの常駐ループ内から張られるため
# プール自体を無効化しても事故らないが、念のため呼び出しごとに新規コネクションを
# 張って確実にクローズすることで、接続の使い回しに起因する不具合の余地を無くす。
_engine = create_async_engine(_resolve_db_url(), future=True, poolclass=NullPool)
AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False)


@event.listens_for(_engine.sync_engine, "connect")
def _enforce_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """新規コネクション確立ごとに、複数プロセス同時アクセス時のSQLITE_BUSYを緩和する
    PRAGMAを強制する。WALは読み取りと書き込みの並行性を確保し、busy_timeoutは
    ロック競合時に即エラーとせず指定ミリ秒だけ再試行させる。"""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=10000")
    finally:
        cursor.close()


class Base(DeclarativeBase):
    pass


class NazokakeItemORM(Base):
    """`nazokake_core.schemas.NazokakeItem` に対応するテーブル。

    result/scores/persona/trend/axis_comments/result_doc_ids はネストしたオブジェクトのため
    JSON列として保存する(Firestoreのドキュメント指向な構造をそのまま引き継ぐ)。
    rss_publisher.py が書き込む「未処理(pending)」キュー行は上記フィールドの大半を
    欠いた部分行であるため、doc_id/odai 以外はすべてNULL許容とする。
    """

    __tablename__ = "nazokake_items"

    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str | None] = mapped_column(String, nullable=True)
    odai: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    nazokake_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    scores: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    s_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall: Mapped[str | None] = mapped_column(Text, nullable=True)
    axis_comments: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # --- apps/evaluator の段階的開示(Progressive Disclosure)フロー用フィールド ---
    # Gemini(主軸)とELYZA/LocalLLM(おまけ)の二重生成を同一行に段階的に書き込むため、
    # おまけ側は "_llmjp" サフィックスで主軸側の同名カラムと分離している。
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[str | None] = mapped_column(String, nullable=True)
    result_gemini: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    llmjp_status: Mapped[str | None] = mapped_column(String, nullable=True)
    result_llmjp: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    nazokake_text_llmjp: Mapped[str | None] = mapped_column(Text, nullable=True)
    scores_llmjp: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    s_total_llmjp: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall_llmjp: Mapped[str | None] = mapped_column(Text, nullable=True)
    axis_comments_llmjp: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    evaluator_model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    persona: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    trend: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    dpo_pair_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str | None] = mapped_column(String, nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String, nullable=True)
    feed_ready: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    eval_status: Mapped[str | None] = mapped_column(String, nullable=True)
    is_user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    is_golden_data: Mapped[bool] = mapped_column(Boolean, default=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    random_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    gemini_status: Mapped[str | None] = mapped_column(String, nullable=True)
    elyza_status: Mapped[str | None] = mapped_column(String, nullable=True)
    locked_at: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    result_doc_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # ユーザー(道場破りフィード)による評価・添削コメントの追記履歴。
    # {"user_score":..., "user_slug":..., "comment":...} のdictをリストで蓄積する。
    human_evaluations: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    # コアーセット・リプレイ(破滅的忘却対策)用のブックキーピング。tools/extract_dataset.pyが
    # このレコードをSFT/DPOデータセットへ実際に含めた直近の時刻(ISO8601)。NULL="未学習
    # (このレコードはまだ一度も学習データセットへ含まれていない)"であり、「未学習の最新
    # データ」プールの判定基準として使う。過去の学習済みデータ(この列がNOT NULL)は、
    # is_golden_data/高評価のものに限り層化抽出でコアーセット(リプレイ用)として
    # 再サンプリングされ得る。
    trained_at: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # --- Firestoreバックアップ同期(一方向Push)用ブックキーピング ---
    # updated_at: ローカルでの最終変更時刻。upsert_item()が呼ばれるたびに必ずサーバー側で
    # 上書きする(呼び出し元が指定した値は無視する)。Firestore側の対応ドキュメントの
    # updated_at と比較し、ローカルの方が新しい場合のみPushする冪等性判定の基準値。
    updated_at: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # sync_status: "pending"(未同期) / "synced"(同期済み) / "error"(直近の同期失敗、リトライ対象) /
    # "fatal"(MAX_SYNC_RETRIES連続失敗によるポイズンピル隔離、get_pending_sync_batchの対象外) /
    # "discarded"(DLQ管理画面からの「破棄」操作、隔離状態を維持したままDLQ一覧の表示対象からも外す)。
    # upsert_item()はローカル内容が変わるたびに必ず"pending"へリセットする
    # (=同期ワーカーの成功/失敗マーキング以外の経路では常に再同期対象とみなす)。
    sync_status: Mapped[str] = mapped_column(String, default="pending", index=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # retry_count: 連続同期失敗回数(ポイズンピル判定用)。upsert_item()でローカル内容が
    # 変わるたびに0へリセットする(=新しい変更は「まだ1度も試していない」とみなす)。
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class AuditLogORM(Base):
    """ポイズンピル(DLQ)操作等に対する不変な監査証跡(Audit Trail)。

    既存データを一切変更しないAppend-onlyのログテーブルであり、このテーブル自身への
    UPDATE/DELETEは想定しない(常にINSERTのみ)。
    """

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    target_item_id: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    # レイアウト破壊を防ぐため、リクエスト内容や詳細なペイロードをJSONへ
    # シリアライズして格納する(改行・カンマ等を含む自由記述テキストでも安全)。
    reason: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String)


class TriggerStateORM(Base):
    """tools/mlops_trigger.pyのマルチ起動トリガーのクールダウン・多重起動防止状態
    (instructions/174)。

    以前はfilelockのmtime(ローカルファイルへの状態依存というアンチパターン)で
    代替していたが、SREの絶対要件に基づきこのDBへ完全移行した。pipeline_id
    ("nazo"/"agent")ごとに「直前に成功裏にキックした時刻」と「そのときのステータス」
    のみを保持する単純な状態レコードであり、AuditLogORMとは異なりAppend-onlyでは
    なく1レコードを継続的にUpsertする。
    """

    __tablename__ = "trigger_state"

    pipeline_id: Mapped[str] = mapped_column(String, primary_key=True)
    # 他の日時系カラム(created_at/updated_at等)と同じ規約でISO8601文字列として
    # 保存する(このコードベース全体でdatetime型カラムは一切使用していない)。
    last_triggered_at: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String)


async def init_db() -> None:
    """テーブルが存在しない場合のみ作成する(既存データは保持される、CREATE TABLE IF NOT EXISTS相当)。"""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


# ------------------------------------------------------------------
# DAO: apps/batch_factory の各ワーカーから利用する、キュー操作込みのCRUD関数群。
# ------------------------------------------------------------------


async def upsert_item(payload: dict[str, Any]) -> None:
    """doc_id をキーに1件をUpsertする(Firestoreの `.set()` と同じ冪等挙動)。

    payload はNazokakeItemの完全なdumpに限らず、rss_publisher.pyが書き込む
    部分dict(doc_id/odai/status/trend/created_atのみ)も受け付ける。

    updated_at と sync_status は呼び出し元がpayloadに含めていても常にサーバー側で
    上書きする(=このローカル変更をFirestoreバックアップ同期の対象として必ず
    "pending" 化する)。retry_count も同様に必ず0へリセットする(=新しい変更は
    まだ1度も同期を試みていないとみなす)。同期ワーカー自身の成功/失敗マーキングは
    mark_synced() / mark_sync_failed() という別経路(このupsert_itemを経由しない)で行う。
    """
    columns = {c.name for c in NazokakeItemORM.__table__.columns}
    row = {k: v for k, v in payload.items() if k in columns}
    row.pop("updated_at", None)
    row.pop("sync_status", None)
    row.pop("retry_count", None)
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    row["sync_status"] = "pending"
    row["retry_count"] = 0
    async with get_session() as session:
        async with session.begin():
            existing = await session.get(NazokakeItemORM, row["doc_id"])
            if existing is None:
                session.add(NazokakeItemORM(**row))
            else:
                for key, value in row.items():
                    setattr(existing, key, value)


async def claim_pending_trend() -> dict[str, Any] | None:
    """status=="pending" の行を1件だけ排他的に "processing" へ遷移させ、内容を返す。

    UPDATE ... WHERE status=="pending" ... RETURNING を1文で発行するため、
    SELECTしてからUPDATEする2段階操作特有のTOCTOU(競合状態)が存在しない。
    SQLiteは書き込みトランザクションを直列化するため、複数ワーカーが同時に
    呼び出しても同一行が二重にclaimされることはない。ロック可能な候補が尽きた
    場合はNoneを返す(呼び出し側でポーリング/リトライする)。
    """
    now = datetime.now(timezone.utc).isoformat()
    async with get_session() as session:
        async with session.begin():
            candidate = await session.execute(
                select(NazokakeItemORM.doc_id)
                .where(NazokakeItemORM.status == "pending")
                .order_by(NazokakeItemORM.created_at)
                .limit(1)
            )
            doc_id = candidate.scalar_one_or_none()
            if doc_id is None:
                return None

            result = await session.execute(
                update(NazokakeItemORM)
                .where(
                    NazokakeItemORM.doc_id == doc_id,
                    NazokakeItemORM.status == "pending",
                )
                .values(
                    status="processing",
                    locked_at=now,
                    updated_at=now,
                    sync_status="pending",
                )
                .returning(NazokakeItemORM)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None  # 他ワーカーに先取りされた
            return {
                c.name: getattr(row, c.name) for c in NazokakeItemORM.__table__.columns
            }


async def mark_trend_completed(doc_id: str, result_doc_ids: list[str]) -> None:
    """ロックしたトレンドキューへ、生成結果(完成品ドキュメントID群)への参照とともに完了ステータスを書き戻す。"""
    now = datetime.now(timezone.utc).isoformat()
    async with get_session() as session:
        async with session.begin():
            await session.execute(
                update(NazokakeItemORM)
                .where(NazokakeItemORM.doc_id == doc_id)
                .values(
                    status="completed",
                    completed_at=now,
                    result_doc_ids=result_doc_ids,
                    updated_at=now,
                    sync_status="pending",
                )
            )


async def get_pending_sync_batch(limit: int = 20) -> list[dict[str, Any]]:
    """sync_status が "pending" または "error"(リトライ対象) の行を最大limit件、
    updated_at昇順(古いものから)で読み取る(読み取り専用、行ロックは取得しない)。

    同期ワーカーは単一プロセスとして稼働する前提のため、claim_pending_trend()の
    ような "processing" 遷移によるロックは行わない。同時に複数の同期ワーカーを
    走らせる運用は想定していない。
    """
    async with get_session() as session:
        result = await session.execute(
            select(NazokakeItemORM)
            .where(NazokakeItemORM.sync_status.in_(["pending", "error"]))
            .order_by(NazokakeItemORM.updated_at)
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {c.name: getattr(row, c.name) for c in NazokakeItemORM.__table__.columns}
            for row in rows
        ]


async def mark_synced(doc_id: str, expected_updated_at: str | None) -> None:
    """Firestoreへの同期に成功した行を "synced" にする。

    WHERE updated_at=expected_updated_at を条件に付けることで、同期処理の実行中に
    別の書き込みでこの行が更に更新されていた場合は0行更新となり(=このmark_syncedは
    黎明のsync_statusを取り消さない)、その新しい変更が次回の同期対象として
    "pending" のまま残る(取りこぼしを防ぐ)。updated_at自体は書き換えない
    (=このメソッドは「ローカル内容が変わった」という意味のブックキーピングには
    影響を与えない)。
    """
    async with get_session() as session:
        async with session.begin():
            await session.execute(
                update(NazokakeItemORM)
                .where(
                    NazokakeItemORM.doc_id == doc_id,
                    NazokakeItemORM.updated_at == expected_updated_at,
                )
                .values(sync_status="synced", last_sync_error=None)
            )


async def mark_sync_failed(doc_id: str, error_message: str) -> None:
    """Firestoreへの同期に失敗した行のretry_countを+1し、失敗理由を残す。

    retry_countがMAX_SYNC_RETRIESに達した場合はsync_status="fatal"へ隔離し
    (ポイズンピル判定)、次回以降のget_pending_sync_batch()の対象から完全に外す。
    未満の場合は"error"(次回の同期ワーカー実行時にリトライ対象として拾われる)。
    updated_atは書き換えない(ローカル内容自体は変化していないため)。
    """
    async with get_session() as session:
        async with session.begin():
            new_retry_count = NazokakeItemORM.retry_count + 1
            await session.execute(
                update(NazokakeItemORM)
                .where(NazokakeItemORM.doc_id == doc_id)
                .values(
                    retry_count=new_retry_count,
                    last_sync_error=error_message[:2000],
                    sync_status=case(
                        (new_retry_count >= MAX_SYNC_RETRIES, "fatal"),
                        else_="error",
                    ),
                )
            )


# ------------------------------------------------------------------
# Serialized Writer: プロセス内の全DB操作を単一の常駐バックグラウンドタスクへ
# 集約し、1件ずつ直列実行する。asyncio.run()をDAO呼び出しごとに乱発する旧実装は、
# 呼び出し元が増えるほど「同時に複数の接続がDBへ殴りかかる」状態を招きやすかった。
# ここでは唯一のコンシューマがキューを順番に処理するため、プロセス内での書き込み
# 競合は構造的に発生しない。
# ------------------------------------------------------------------


class _SerializedWriter:
    """常駐イベントループを1本のバックグラウンドスレッドで走らせ、その中で単一の
    コンシューマタスクがasyncio.Queueを消費してDB操作を1件ずつ直列実行する。

    同期コード(各ワーカー)は submit() 経由でのみDB操作を依頼できる。submit() は
    タスクをキューへpushし、Serialized Writerが処理した結果(または例外)を待って
    返す薄いブリッジであり、呼び出し元自身がDBコネクションを直接開くことはない。
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_lock = threading.Lock()

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._queue = asyncio.Queue()
        loop.create_task(self._consume())
        self._ready.set()
        loop.run_forever()

    async def _consume(self) -> None:
        assert self._queue is not None
        while True:
            coro_factory, result_future = await self._queue.get()
            try:
                result = await coro_factory()
            except Exception as exc:  # noqa: BLE001 - 呼び出し元へそのまま伝播させる
                if not result_future.cancelled():
                    result_future.set_exception(exc)
                continue
            if not result_future.cancelled():
                result_future.set_result(result)

    def _ensure_started(self) -> None:
        if self._thread is not None:
            return
        with self._start_lock:
            if self._thread is not None:
                return
            thread = threading.Thread(
                target=self._run_loop, name="nazokake-db-serialized-writer", daemon=True
            )
            thread.start()
            self._ready.wait()
            self._thread = thread

    def submit(self, coro_factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
        """coro_factory()をSerialized Writerのキューへpushし、処理結果を待って返す。

        同期呼び出し元(main.py/rss_publisher.py等、常駐イベントループを持たない
        スクリプト)向け。concurrent.futures.Future.result()でブロッキング待機する。
        """
        self._ensure_started()
        assert self._loop is not None and self._queue is not None
        result_future: concurrent.futures.Future = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait, (coro_factory, result_future)
        )
        return result_future.result()

    async def submit_async(
        self, coro_factory: Callable[[], Coroutine[Any, Any, T]]
    ) -> T:
        """coro_factory()をSerialized Writerのキューへpushし、呼び出し元のイベント
        ループをブロックせずに処理結果を待つ。

        FastAPI(uvicorn)のような常駐イベントループから呼ぶ場合は必ずこちらを使うこと。
        submit()は別スレッドの結果をconcurrent.futures.Future.result()で同期的に
        ブロック待機するため、イベントループのスレッドから直接呼ぶとそのループ全体
        (=サーバーが処理中の他の全リクエスト)が待機中フリーズしてしまう。
        asyncio.wrap_future()でconcurrent.futures.Futureをこのループのasyncio.Futureへ
        橋渡しし、awaitで非ブロッキングに結果を受け取る。
        """
        self._ensure_started()
        assert self._loop is not None and self._queue is not None
        result_future: concurrent.futures.Future = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait, (coro_factory, result_future)
        )
        return await asyncio.wrap_future(result_future)


_serialized_writer = _SerializedWriter()


def ensure_db_ready() -> None:
    """DBファイルとテーブルをローカルに用意する(Serialized Writer経由)。"""
    _serialized_writer.submit(init_db)


def sync_upsert_item(payload: dict[str, Any]) -> None:
    _serialized_writer.submit(lambda: upsert_item(payload))


def sync_claim_pending_trend() -> dict[str, Any] | None:
    return _serialized_writer.submit(claim_pending_trend)


def sync_mark_trend_completed(doc_id: str, result_doc_ids: list[str]) -> None:
    _serialized_writer.submit(lambda: mark_trend_completed(doc_id, result_doc_ids))


def sync_get_pending_sync_batch(limit: int = 20) -> list[dict[str, Any]]:
    return _serialized_writer.submit(lambda: get_pending_sync_batch(limit))


def sync_mark_synced(doc_id: str, expected_updated_at: str | None) -> None:
    _serialized_writer.submit(lambda: mark_synced(doc_id, expected_updated_at))


def sync_mark_sync_failed(doc_id: str, error_message: str) -> None:
    _serialized_writer.submit(lambda: mark_sync_failed(doc_id, error_message))


# ------------------------------------------------------------------
# 非同期呼び出し元(FastAPI等、常駐イベントループ上で動くワーカー)向けインターフェース。
# 【絶対制約】LLM推論を待機している間はDB接続を保持しない: 呼び出し元は
# async_upsert_item() を単発で都度呼ぶこと(内部でopen→commit→closeが完結する)。
# 複数回の更新をまとめて1回のセッション/トランザクションに詰め込んではならない。
# ------------------------------------------------------------------


async def async_upsert_item(payload: dict[str, Any]) -> None:
    """upsert_item()のSerialized Writer経由・非ブロッキング版。"""
    await _serialized_writer.submit_async(lambda: upsert_item(payload))


async def append_audit_log(
    target_item_id: str, actor: str, action: str, reason_dict: dict[str, Any]
) -> None:
    """監査ログを1件追記する(Append-only、既存データの更新・削除は一切行わない)。"""
    async with get_session() as session:
        async with session.begin():
            session.add(
                AuditLogORM(
                    id=str(uuid.uuid4()),
                    target_item_id=target_item_id,
                    actor=actor,
                    action=action,
                    reason=reason_dict,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )


async def async_append_audit_log(
    target_item_id: str, actor: str, action: str, reason_dict: dict[str, Any]
) -> None:
    """append_audit_log()のSerialized Writer経由・非ブロッキング版。"""
    await _serialized_writer.submit_async(
        lambda: append_audit_log(target_item_id, actor, action, reason_dict)
    )


async def async_get_item(doc_id: str) -> dict[str, Any] | None:
    """doc_idで1件読み取る(読み取り専用)。

    WALモードは複数コネクションからの並行読み取りを許すため、書き込みを直列化する
    Serialized Writerのキューを経由せず、専用の短命セッションで直接読む
    (ポーリング用途で頻繁に呼ばれるため、単一の書き込みキューの後ろに並ばせない)。
    """
    async with get_session() as session:
        row = await session.get(NazokakeItemORM, doc_id)
        if row is None:
            return None
        return {c.name: getattr(row, c.name) for c in NazokakeItemORM.__table__.columns}


async def async_get_dlq_items() -> list[dict[str, Any]]:
    """DLQ(sync_status=="fatal"、ポイズンピル隔離済み)の行を全カラムで取得する。

    _row_to_ui_dict()とは異なり、sync_status/last_sync_error/retry_countを意図的に
    含める(隔離理由そのものを見せることがDLQ管理画面の目的のため)。updated_at降順。
    """
    async with get_session() as session:
        result = await session.execute(
            select(NazokakeItemORM)
            .where(NazokakeItemORM.sync_status == "fatal")
            .order_by(NazokakeItemORM.updated_at.desc())
        )
        rows = result.scalars().all()
        return [
            {c.name: getattr(row, c.name) for c in NazokakeItemORM.__table__.columns}
            for row in rows
        ]


async def async_get_audit_logs(limit: int = 100) -> list[dict[str, Any]]:
    """audit_logsテーブルの監査証跡を、created_at降順(新しい順)で最大limit件取得する。

    Append-onlyな不変ログであり、このDAO自身も読み取り専用(UPDATE/DELETEは行わない)。
    """
    async with get_session() as session:
        result = await session.execute(
            select(AuditLogORM).order_by(AuditLogORM.created_at.desc()).limit(limit)
        )
        rows = result.scalars().all()
        return [
            {c.name: getattr(row, c.name) for c in AuditLogORM.__table__.columns}
            for row in rows
        ]


async def async_retry_dlq_item(
    doc_id: str, *, actor: str = "system", reason_dict: dict[str, Any] | None = None
) -> bool:
    """DLQからの「再試行」: sync_statusをpendingへ戻し、retry_count/last_sync_errorを
    リセットする(次回の同期ワーカー実行時に再送対象となる)。対象が存在しないか、
    既にfatal(隔離中)でない場合はFalseを返す(呼び出し元はこれを404判定に使う)。

    ステータス更新と監査証跡(audit_logs)への追記を単一のトランザクション内で行う。
    いずれかが失敗した場合は両方ロールバックされ、「操作(破壊的なステータス変更)は
    成功したのに対応する監査証跡が残っていない」という不整合を構造的に排除する。
    """
    async with get_session() as session:
        async with session.begin():
            row = await session.get(NazokakeItemORM, doc_id)
            if row is None or row.sync_status != "fatal":
                return False
            row.sync_status = "pending"
            row.retry_count = 0
            row.last_sync_error = None
            session.add(
                AuditLogORM(
                    id=str(uuid.uuid4()),
                    target_item_id=doc_id,
                    actor=actor,
                    action="RETRY_DLQ",
                    reason=reason_dict,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        return True


async def async_discard_dlq_item(
    doc_id: str, *, actor: str = "system", reason_dict: dict[str, Any] | None = None
) -> bool:
    """DLQからの「破棄」: 隔離状態は維持したままsync_statusを"discarded"にし、
    get_pending_sync_batch()およびDLQ一覧(async_get_dlq_items())の両方の対象から
    外す。対象が存在しないか、既にfatal(隔離中)でない場合はFalseを返す。

    ステータス更新と監査証跡(audit_logs)への追記を単一のトランザクション内で行う
    (async_retry_dlq_itemと同じ設計。破棄は復元不能な操作のため、監査証跡の
    確実な同時記録が特に重要)。
    """
    async with get_session() as session:
        async with session.begin():
            row = await session.get(NazokakeItemORM, doc_id)
            if row is None or row.sync_status != "fatal":
                return False
            row.sync_status = "discarded"
            session.add(
                AuditLogORM(
                    id=str(uuid.uuid4()),
                    target_item_id=doc_id,
                    actor=actor,
                    action="DISCARD_DLQ",
                    reason=reason_dict,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        return True


def _row_to_ui_dict(row: NazokakeItemORM) -> dict[str, Any]:
    """ORM行をUI向けdictへ変換する。

    【絶対制約】クラウドへの同期状態(sync_status/last_sync_error)は描画のブロック
    条件として一切使わせないため、レスポンスから除外する。
    """
    return {
        c.name: getattr(row, c.name)
        for c in NazokakeItemORM.__table__.columns
        if c.name not in ("sync_status", "last_sync_error")
    }


async def async_get_feed_items(
    limit: int = 5, cursor_random_weight: float | None = None
) -> list[dict[str, Any]]:
    """道場破りフィード(案C: 乱数フィールドハック)をrandom_weight降順でシークする。

    カーソル無し(1バッチ目)でヒットが0件の場合のみ、末尾から先頭への巡回シークの
    フォールバックとして先頭(random_weight最大)から再取得する。
    """
    async with get_session() as session:
        stmt = select(NazokakeItemORM).where(NazokakeItemORM.feed_ready.is_(True))
        if cursor_random_weight is not None:
            stmt = stmt.where(NazokakeItemORM.random_weight < cursor_random_weight)
        stmt = stmt.order_by(NazokakeItemORM.random_weight.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        if not rows and cursor_random_weight is not None:
            fallback_stmt = (
                select(NazokakeItemORM)
                .where(NazokakeItemORM.feed_ready.is_(True))
                .order_by(NazokakeItemORM.random_weight.desc())
                .limit(limit)
            )
            rows = (await session.execute(fallback_stmt)).scalars().all()
        return [_row_to_ui_dict(row) for row in rows]


async def async_get_golden_feed_items(
    limit: int = 5, cursor_created_at: str | None = None
) -> list[dict[str, Any]]:
    """殿堂入り(golden)フィードをcreated_at降順でシークする。"""
    async with get_session() as session:
        golden_filter = or_(
            NazokakeItemORM.gemini_status == "golden",
            NazokakeItemORM.elyza_status == "golden",
            NazokakeItemORM.is_golden_data.is_(True),
        )
        stmt = select(NazokakeItemORM).where(golden_filter)
        if cursor_created_at is not None:
            stmt = stmt.where(NazokakeItemORM.created_at < cursor_created_at)
        stmt = stmt.order_by(NazokakeItemORM.created_at.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [_row_to_ui_dict(row) for row in rows]


async def async_append_human_evaluation(
    doc_id: str, evaluation_entry: dict[str, Any], comment_entry: dict[str, Any]
) -> bool:
    """対象なぞかけへ、道場破りフィード経由のユーザー評価とコメントを1件追記する。

    対象が存在しない場合はFalseを返す(呼び出し元はこれを404判定に使う)。
    """
    async with get_session() as session:
        async with session.begin():
            row = await session.get(NazokakeItemORM, doc_id)
            if row is None:
                return False
            entries = list(row.human_evaluations or [])
            entries.append({**evaluation_entry, **comment_entry})
            row.human_evaluations = entries
        return True


async def async_mark_trained(doc_ids: list[str]) -> None:
    """コアーセット・リプレイのブックキーピング: 指定doc_id群のtrained_atを現在時刻へ
    更新する(=このレコードが実際に学習データセットへ含まれたことを記録する)。

    tools/extract_dataset.pyが「未学習の最新データ」プールから今回サンプリングした
    レコードに対してのみ呼び出す(既に学習済み=リプレイ用コアーセットとして再サンプル
    されたレコードのtrained_atは、意図的に更新しない=最初に学習された時刻を保持する)。
    """
    if not doc_ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    async with get_session() as session:
        async with session.begin():
            await session.execute(
                update(NazokakeItemORM)
                .where(NazokakeItemORM.doc_id.in_(doc_ids))
                .values(trained_at=now)
            )


async def async_get_trigger_state(pipeline_id: str) -> dict[str, Any] | None:
    """trigger_stateレコードを1件取得する(instructions/174)。

    レコードが存在しない場合はNoneを返す(=このpipeline_idは一度もキックされて
    いない。呼び出し元はクールダウン対象外・多重起動の懸念無しとして扱ってよい)。
    """
    async with get_session() as session:
        row = await session.get(TriggerStateORM, pipeline_id)
        if row is None:
            return None
        return {
            "pipeline_id": row.pipeline_id,
            "last_triggered_at": row.last_triggered_at,
            "status": row.status,
        }


async def async_record_trigger_kick(pipeline_id: str, status: str = "triggered") -> None:
    """パイプラインを正常にキックした直後、trigger_stateレコードを現在時刻と
    ステータスでアトミックにUpsertする(instructions/174、upsert_item()と同じ
    get→分岐→session.begin()による単一トランザクションのパターン)。
    """
    now = datetime.now(timezone.utc).isoformat()
    async with get_session() as session:
        async with session.begin():
            existing = await session.get(TriggerStateORM, pipeline_id)
            if existing is None:
                session.add(
                    TriggerStateORM(
                        pipeline_id=pipeline_id, last_triggered_at=now, status=status
                    )
                )
            else:
                existing.last_triggered_at = now
                existing.status = status

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
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, TypeVar

from sqlalchemy import JSON, Boolean, Float, String, Text, event, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

DEFAULT_DB_PATH = "nazokake_local.db"

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
    axis_comments_llmjp: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
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
    """
    columns = {c.name for c in NazokakeItemORM.__table__.columns}
    row = {k: v for k, v in payload.items() if k in columns}
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
                .where(NazokakeItemORM.doc_id == doc_id, NazokakeItemORM.status == "pending")
                .values(status="processing", locked_at=now)
                .returning(NazokakeItemORM)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None  # 他ワーカーに先取りされた
            return {c.name: getattr(row, c.name) for c in NazokakeItemORM.__table__.columns}


async def mark_trend_completed(doc_id: str, result_doc_ids: list[str]) -> None:
    """ロックしたトレンドキューへ、生成結果(完成品ドキュメントID群)への参照とともに完了ステータスを書き戻す。"""
    now = datetime.now(timezone.utc).isoformat()
    async with get_session() as session:
        async with session.begin():
            await session.execute(
                update(NazokakeItemORM)
                .where(NazokakeItemORM.doc_id == doc_id)
                .values(status="completed", completed_at=now, result_doc_ids=result_doc_ids)
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
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (coro_factory, result_future))
        return result_future.result()

    async def submit_async(self, coro_factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
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
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (coro_factory, result_future))
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


# ------------------------------------------------------------------
# 非同期呼び出し元(FastAPI等、常駐イベントループ上で動くワーカー)向けインターフェース。
# 【絶対制約】LLM推論を待機している間はDB接続を保持しない: 呼び出し元は
# async_upsert_item() を単発で都度呼ぶこと(内部でopen→commit→closeが完結する)。
# 複数回の更新をまとめて1回のセッション/トランザクションに詰め込んではならない。
# ------------------------------------------------------------------

async def async_upsert_item(payload: dict[str, Any]) -> None:
    """upsert_item()のSerialized Writer経由・非ブロッキング版。"""
    await _serialized_writer.submit_async(lambda: upsert_item(payload))


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

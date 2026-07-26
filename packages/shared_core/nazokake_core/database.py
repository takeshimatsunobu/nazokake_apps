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
import logging
import os
import threading
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    Integer,
    String,
    Text,
    and_,
    case,
    event,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

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
    """tools/mlops_trigger.pyのマルチ起動トリガーの状態(instructions/174、および
    「排他制御(Mutex)」と「実行間隔制御(Cooldown)」の分離に関する追補修正)。

    以前はfilelockのmtime(ローカルファイルへの状態依存というアンチパターン)で
    代替していたが、SREの絶対要件に基づきこのDBへ完全移行した。pipeline_id
    ("nazo"/"agent")ごとに1レコードを継続的にUpsertする(AuditLogORMとは異なり
    Append-onlyではない)。

    【排他制御(Mutex)とクールダウンの分離】完了時に単に「解放(idle)」するだけでは
    クールダウンそのものが破壊され、次回のトリガー評価が即座に再起動してしまう
    (無限ループのデグレード)。このため、2つの時刻カラムの役割を明確に分離する:
      - last_triggered_at: 直前にclaim(起動権を奪取)した時刻。排他制御・
        ハードクラッシュ(OOM Killer/SIGKILL)からのゾンビ回収(stale_after_hours
        経過による自動パージ)の判定にのみ使う。
      - last_completed_at: 直前に正常完了(success=True)した時刻。クールダウン
        (cooldown_hours)の起点はここのみで、statusの遷移からは独立している。
    """

    __tablename__ = "trigger_state"

    pipeline_id: Mapped[str] = mapped_column(String, primary_key=True)
    # 他の日時系カラム(created_at/updated_at等)と同じ規約でISO8601文字列として
    # 保存する(このコードベース全体でdatetime型カラムは一切使用していない)。
    last_triggered_at: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    last_completed_at: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String)


class QualityCircuitBreakerStateORM(Base):
    """Agent自身の推論出力品質のサイレント・デグレード検知状態(instructions/182、
    スライディングウィンドウ方式への是正はinstructions/183)。

    TriggerStateORMと同じ規約(pipeline_idごとに1行を継続的にUpsertする、
    Append-onlyではない)。2つの独立した軸を同一行で追跡する:
      - 評価スコアの極端値(extreme_window): なぞかけ評価スコアがスケールの
        最高/最低に偏っているかどうかのサイレント・デグレード。
      - エラー・パース失敗(error_window): 生成/評価の試行が失敗したかどうかの
        サイレント・デグレード。

    【instructions/183是正: 連続カウント方式(consecutive_*)からスライディング
    ウィンドウ方式への変更】連続カウント方式は、確率的モデルのノイズ(まぐれ当たり
    1回)だけで連続回数が0へリセットされてしまい、実際には劣化が続いているのに
    Tripしない(検知漏れ、Flapping脆弱性)という欠陥があった。各軸を「直近
    window_size件のうち何件が異常だったか」を保持するブール値のFIFOキュー
    (extreme_window/error_window)として持たせ、異常件数がanomaly_threshold以上に
    達した時点でTripとみなす方式へ変更する。個々の判定・しきい値の適用は
    quality_circuit_breaker.py側の責務であり、この層は生のウィンドウ状態のみを
    保持する。
    """

    __tablename__ = "quality_circuit_breaker_state"

    pipeline_id: Mapped[str] = mapped_column(String, primary_key=True)
    # 直近window_size件の評価スコア極端値判定(True=極端値)を古い順に保持する
    # FIFOキュー。window_sizeを超えた古い要素は先頭から切り詰める。
    extreme_window: Mapped[list[bool] | None] = mapped_column(JSON, nullable=True)
    # 直近に記録された極端値の方向("high"/"low")。診断・アラート文言表示専用であり、
    # Trip判定そのものには使わない(方向が高低で入れ替わるFlapping自体も、
    # extreme_windowの異常件数として正しく積算されるため)。
    last_extreme_direction: Mapped[str | None] = mapped_column(String, nullable=True)
    # 直近window_size件のパイプライン試行結果(True=失敗)を古い順に保持するFIFOキュー。
    error_window: Mapped[list[bool] | None] = mapped_column(JSON, nullable=True)
    last_error_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    tripped_at: Mapped[str | None] = mapped_column(String, nullable=True)


class ResearchArticleORM(Base):
    """instructions/231: 「なぞかけ研究所」記事データ基盤(ResearchArticle Pydanticモデルの
    永続化先)。main_category > sub_category > title の3階層でカテゴライズされた
    研究記事を保持する。

    created_at/updated_atは、このコードベース全体の規約(TriggerStateORM等参照)に
    従い、datetime型カラムではなくISO8601文字列として保存する。
    """

    __tablename__ = "research_articles"

    article_id: Mapped[str] = mapped_column(String, primary_key=True)
    main_category: Mapped[str] = mapped_column(String, index=True)
    sub_category: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)


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


# instructions/240: 起動時リストアで一括挿入する際、NOT NULL制約かつPython側
# defaultを持つ列(feed_ready/status/is_user_edited/is_golden_data/is_approved/
# sync_status/retry_count)は、Core経由の複数行insertではORMのdefault=が
# 自動適用されない(キーが明示的にNoneだとNULLをそのままバインドしてしまい
# NOT NULL制約違反になる)。Firestore側のドキュメントにキー自体が無かった場合
# にのみ、この既定値で補う。
_NAZOKAKE_ITEM_BULK_DEFAULTS: dict[str, Any] = {
    "feed_ready": True,
    "status": "pending",
    "is_user_edited": False,
    "is_golden_data": False,
    "is_approved": False,
    "sync_status": "synced",  # Firestoreから来た時点で定義上「既に同期済み」
    "retry_count": 0,
}


async def async_bulk_restore_items_if_missing(rows: list[dict[str, Any]]) -> tuple[int, int]:
    """instructions/240: Firestoreからの起動時リストア専用の一括挿入。

    1件ずつsession.get()で存在確認してから個別commitする方式は、実際の
    nazokake_itemsコレクションの規模(実測1万件超)ではCloud Runの起動を
    数分間ブロックしてしまい実用にならないため、SQLiteのINSERT OR IGNORE相当
    (on_conflict_do_nothing、doc_id基準)で複数件を1回のトランザクションに
    まとめて処理する。呼び出し元(firestore_sync.py)がSQLiteのホスト
    パラメータ数上限を避けるための適度なチャンクサイズに分割して渡す前提。

    SQLAlchemy Coreの複数行insertは全行が同一のキー集合を持つ必要があるため、
    ORMの全カラムを基準に各行を正規化する(欠けているキーは、NOT NULL制約を
    持つ列のみ_NAZOKAKE_ITEM_BULK_DEFAULTSで補い、その他はNULL許容なのでNoneのまま)。

    戻り値は (このバッチでの新規挿入件数, 既存のためスキップされた件数)。
    """
    if not rows:
        return 0, 0

    columns = [c.name for c in NazokakeItemORM.__table__.columns]
    filtered_rows = []
    for payload in rows:
        if not payload.get("doc_id") or not payload.get("odai"):
            continue
        row = {
            col: (payload[col] if col in payload else _NAZOKAKE_ITEM_BULK_DEFAULTS.get(col))
            for col in columns
        }
        filtered_rows.append(row)

    if not filtered_rows:
        return 0, 0

    async with get_session() as session:
        async with session.begin():
            stmt = sqlite_insert(NazokakeItemORM).values(filtered_rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["doc_id"])
            result = await session.execute(stmt)
            inserted = result.rowcount if result.rowcount and result.rowcount > 0 else 0

    return inserted, len(filtered_rows) - inserted


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


# ------------------------------------------------------------------
# なぞかけ研究所(instructions/231, 233): 公開済み記事の一覧・詳細取得DAO。
# 下書き(is_published=False)は一般ユーザー向けAPIの対象外とする。
# ------------------------------------------------------------------


async def async_get_published_research_articles() -> list[dict[str, Any]]:
    """公開済み記事の一覧を、main_category > sub_category でのグルーピング表示が
    安定するようmain_category → sub_category → created_at昇順で返す。一覧表示では
    本文(content)を使わないため、レスポンスサイズを抑える目的で含めない。
    """
    async with get_session() as session:
        stmt = (
            select(ResearchArticleORM)
            .where(ResearchArticleORM.is_published.is_(True))
            .order_by(
                ResearchArticleORM.main_category,
                ResearchArticleORM.sub_category,
                ResearchArticleORM.created_at,
            )
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "article_id": row.article_id,
                "main_category": row.main_category,
                "sub_category": row.sub_category,
                "title": row.title,
                "created_at": row.created_at,
            }
            for row in rows
        ]


async def async_get_research_article(article_id: str) -> dict[str, Any] | None:
    """公開済み記事を1件、本文込みで取得する。下書きまたは存在しない場合はNoneを返す
    (呼び出し元のルーターはこれを404として扱う)。
    """
    async with get_session() as session:
        row = await session.get(ResearchArticleORM, article_id)
        if row is None or not row.is_published:
            return None
        return {
            "article_id": row.article_id,
            "main_category": row.main_category,
            "sub_category": row.sub_category,
            "title": row.title,
            "content": row.content,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }


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


async def async_try_claim_trigger_slot(
    pipeline_id: str, cooldown_hours: float, stale_after_hours: float
) -> bool:
    """トリガーのクールダウン判定・ゾンビ回収・排他制御(Mutex)のclaim奪取を、
    単一のUPSERT文でアトミックに行う(instructions/174追補: CASパターン)。

    Pythonコード上での`if status == 'running':`という判定は、SELECTと後続のUPDATEの
    間に他プロセスが介入できるレースコンディションを誘発するため採用しない。
    「排他制御(Mutex、多重起動防止+ハードクラッシュからの自己修復)」と
    「実行間隔制御(Cooldown、前回の正常完了からの経過時間)」を明確に分離して
    評価する:

      条件A(排他&ゾンビ回収): status != "running" である、または
        status == "running" のままだが last_triggered_at(直前にclaimした時刻)
        から stale_after_hours 以上経過している(=OOM Killer/SIGKILL等で正常
        終了処理が一切走らなかったと決定論的にみなし、claimを自動的に回収する)。
      条件B(クールダウン): last_completed_at(直前に正常完了した時刻)が
        未設定、または cooldown_hours 以上経過している。

    両方を満たした場合のみ status="running" へ遷移させ(claim成功)、
    影響行数1を返す(=呼び出し元はキックしてよい)。それ以外は影響行数0のまま
    (claim失敗、既に実行中またはクールダウン中のため呼び出し元は見送るべき)。

    【可観測性(SRE監査追補)】ゾンビ回収(OOM Killer/SIGKILL等でstatus="running"の
    まま正常終了処理が走らずstale_after_hours以上経過したケース)は、上記のCAS
    UPSERTだけではSQLエンジン内でサイレントに上書きされ、「前回パイプラインが
    異常死した」というインシデントの事実がどこにも記録されない。このため、
    UPSERT発行の直前にsession.get()で現在の状態を読み、ゾンビ回収が行われる
    条件に該当する場合のみ明示的にlogger.warning()を発出する。この読み取りは
    あくまでログ発出(テレメトリ)目的であり、実際の状態遷移は後続のUPSERTで
    アトミックに担保されるため、読み取り結果に基づいて分岐する実際のロジックは
    存在せず、レースコンディションの懸念はない。
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    cooldown_cutoff = (now - timedelta(hours=cooldown_hours)).isoformat()
    stale_cutoff = (now - timedelta(hours=stale_after_hours)).isoformat()

    stmt = sqlite_insert(TriggerStateORM).values(
        pipeline_id=pipeline_id,
        status="running",
        last_triggered_at=now_iso,
        last_completed_at=None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["pipeline_id"],
        set_={"status": "running", "last_triggered_at": now_iso},
        where=and_(
            or_(
                TriggerStateORM.status != "running",
                TriggerStateORM.last_triggered_at < stale_cutoff,
            ),
            or_(
                TriggerStateORM.last_completed_at.is_(None),
                TriggerStateORM.last_completed_at < cooldown_cutoff,
            ),
        ),
    )
    async with get_session() as session:
        async with session.begin():
            existing = await session.get(TriggerStateORM, pipeline_id)
            if (
                existing is not None
                and existing.status == "running"
                and existing.last_triggered_at is not None
                and existing.last_triggered_at < stale_cutoff
            ):
                logger.warning(
                    f"🚨 [SRE Anomaly] パイプライン {pipeline_id} のゾンビ状態"
                    "(クラッシュ)を検知しました。強制リカバリを実行します。"
                )
            result = await session.execute(stmt)
            return result.rowcount == 1


async def async_release_trigger_slot(pipeline_id: str, *, success: bool) -> None:
    """パイプライン完了時、排他制御(status)とクールダウン起点(last_completed_at)を
    明確に分離して記録する(instructions/174追補)。

    単に「解放(idle)」するだけではクールダウンそのものが破壊され、次回のトリガー
    評価が即座に再起動してしまう(無限ループのデグレード)ため、正常終了と異常終了で
    以下のように扱いを分ける:
      - 正常終了(success=True): status="success"、last_completed_at=NOWを記録し、
        次回のクールダウンの起点とする。
      - 異常終了(success=False): status="failed"のみ更新し、last_completed_atは
        意図的に更新しない(=クールダウンを開始させず、次回トリガー時に即時
        リトライ可能な状態のままにする)。
    """
    async with get_session() as session:
        async with session.begin():
            existing = await session.get(TriggerStateORM, pipeline_id)
            if existing is None:
                # claimがDBに残っていない状況は想定外だが、安全側に倒して
                # 完了報告自体は必ず記録する。
                existing = TriggerStateORM(pipeline_id=pipeline_id, status="idle")
                session.add(existing)
            if success:
                existing.status = "success"
                existing.last_completed_at = datetime.now(timezone.utc).isoformat()
            else:
                existing.status = "failed"


# ------------------------------------------------------------------
# 品質のサーキットブレーカー(instructions/182): Agent自身の推論出力(なぞかけ評価
# スコア/エラー・パース失敗)のサイレント・デグレード検知に使う状態更新DAO。
# 評価スコア系(consecutive_extreme_*)とエラー系(consecutive_error_*)は呼び出し
# タイミングが異なる独立した軸であり、片方の呼び出しがもう片方の連続回数を意図せず
# リセットしてしまわないよう、更新対象カラムそのものを2つの関数へ分離する
# (是否を判定・例外を送出する責務はnazokake_core.quality_circuit_breaker側)。
# ------------------------------------------------------------------


def _push_sliding_window(
    window: list[bool] | None, is_anomalous: bool, window_size: int
) -> list[bool]:
    """スライディングウィンドウ(FIFO)へ今回の判定(True=異常)を1件追加し、
    window_sizeを超えた古い要素を先頭から切り詰める(instructions/183)。
    """
    updated = list(window or [])
    updated.append(is_anomalous)
    if len(updated) > window_size:
        updated = updated[-window_size:]
    return updated


async def _record_evaluation_score_event(
    pipeline_id: str,
    *,
    is_extreme: bool,
    direction: str | None,
    window_size: int,
    anomaly_threshold: int,
) -> dict[str, Any]:
    """QualityCircuitBreakerStateORMの評価スコア系カラム(extreme_window/
    last_extreme_direction)のみを更新する。直近window_size件のうちanomaly_threshold件
    以上が極端値であればTripとみなす(instructions/183: 連続カウント方式は
    まぐれ当たり1回でリセットされ検知漏れを起こすため廃止)。
    """
    async with get_session() as session:
        async with session.begin():
            existing = await session.get(QualityCircuitBreakerStateORM, pipeline_id)
            if existing is None:
                existing = QualityCircuitBreakerStateORM(pipeline_id=pipeline_id)
                session.add(existing)

            existing.extreme_window = _push_sliding_window(
                existing.extreme_window, is_extreme, window_size
            )
            if is_extreme:
                existing.last_extreme_direction = direction

            anomaly_count = sum(existing.extreme_window)
            tripped = anomaly_count >= anomaly_threshold
            if tripped:
                existing.tripped_at = datetime.now(timezone.utc).isoformat()

            return {
                "tripped": tripped,
                "anomaly_count": anomaly_count,
                "window_size": len(existing.extreme_window),
            }


async def _record_pipeline_outcome_event(
    pipeline_id: str,
    *,
    error_signature: str | None,
    window_size: int,
    anomaly_threshold: int,
) -> dict[str, Any]:
    """QualityCircuitBreakerStateORMのエラー系カラム(error_window/
    last_error_signature)のみを更新する。error_signature=Noneは「今回の試行は成功した」
    ことを意味し、ウィンドウには"正常"(False)を積む。同一シグネチャの一致を要求しない
    ため、エラー内容が毎回変わるFlapping(instructions/183が指摘した検知漏れの一種)も、
    直近window_size件のうちanomaly_threshold件以上が「何らかの失敗」であれば検知できる。
    """
    async with get_session() as session:
        async with session.begin():
            existing = await session.get(QualityCircuitBreakerStateORM, pipeline_id)
            if existing is None:
                existing = QualityCircuitBreakerStateORM(pipeline_id=pipeline_id)
                session.add(existing)

            is_error = error_signature is not None
            existing.error_window = _push_sliding_window(
                existing.error_window, is_error, window_size
            )
            existing.last_error_signature = error_signature

            anomaly_count = sum(existing.error_window)
            tripped = anomaly_count >= anomaly_threshold
            if tripped:
                existing.tripped_at = datetime.now(timezone.utc).isoformat()

            return {
                "tripped": tripped,
                "anomaly_count": anomaly_count,
                "window_size": len(existing.error_window),
            }


async def async_get_circuit_breaker_tripped_at(pipeline_id: str) -> str | None:
    """指定pipeline_idのQualityCircuitBreakerStateORM.tripped_atを読み取る
    (読み取り専用、instructions/183のトリガー側Pre-flight Gateから利用する)。
    行が存在しない、またはまだTripしていない場合はNoneを返す。
    """
    async with get_session() as session:
        existing = await session.get(QualityCircuitBreakerStateORM, pipeline_id)
        return existing.tripped_at if existing is not None else None


def sync_record_evaluation_score_event(
    pipeline_id: str,
    *,
    is_extreme: bool,
    direction: str | None,
    window_size: int,
    anomaly_threshold: int,
) -> dict[str, Any]:
    """_record_evaluation_score_event()のSerialized Writer経由・同期版(apps/batch_factory向け)。"""
    return _serialized_writer.submit(
        lambda: _record_evaluation_score_event(
            pipeline_id,
            is_extreme=is_extreme,
            direction=direction,
            window_size=window_size,
            anomaly_threshold=anomaly_threshold,
        )
    )


async def async_record_evaluation_score_event(
    pipeline_id: str,
    *,
    is_extreme: bool,
    direction: str | None,
    window_size: int,
    anomaly_threshold: int,
) -> dict[str, Any]:
    """_record_evaluation_score_event()のSerialized Writer経由・非ブロッキング版(apps/evaluator向け)。"""
    return await _serialized_writer.submit_async(
        lambda: _record_evaluation_score_event(
            pipeline_id,
            is_extreme=is_extreme,
            direction=direction,
            window_size=window_size,
            anomaly_threshold=anomaly_threshold,
        )
    )


def sync_record_pipeline_outcome_event(
    pipeline_id: str, *, error_signature: str | None, window_size: int, anomaly_threshold: int
) -> dict[str, Any]:
    """_record_pipeline_outcome_event()のSerialized Writer経由・同期版(apps/batch_factory向け)。"""
    return _serialized_writer.submit(
        lambda: _record_pipeline_outcome_event(
            pipeline_id,
            error_signature=error_signature,
            window_size=window_size,
            anomaly_threshold=anomaly_threshold,
        )
    )


async def async_record_pipeline_outcome_event(
    pipeline_id: str, *, error_signature: str | None, window_size: int, anomaly_threshold: int
) -> dict[str, Any]:
    """_record_pipeline_outcome_event()のSerialized Writer経由・非ブロッキング版(apps/evaluator向け)。"""
    return await _serialized_writer.submit_async(
        lambda: _record_pipeline_outcome_event(
            pipeline_id,
            error_signature=error_signature,
            window_size=window_size,
            anomaly_threshold=anomaly_threshold,
        )
    )

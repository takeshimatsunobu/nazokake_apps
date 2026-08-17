"""
nazokake_core/firestore_sync.py
==================================
ローカルSQLite(Local SSoT)とFirestoreの間のバックアップ同期(Push)と、
Cloud Run起動時の復元(Pull、instructions/240)。

【Push: sync_once() / sync_once_safe()】sync_status=="pending"/"error" の行を取り、
firebase_adminでFirestoreの対象コレクションへPush(冪等/Upsert)する。冪等性と
順序逆転防止のため、Firestore上の既存ドキュメントのupdated_at を確認し、ローカルの
updated_at が同じかそれより新しい場合のみ上書きする(Firestoreトランザクション内で
判定と書き込みをアトミックに行う)。失敗時はローカルのsync_statusを"error"にし、
次回実行時にリトライ対象として再度拾い上げる(デッドレター的リトライキュー)。

【Pull: async_restore_from_firestore()】Cloud Run上のSQLite(/tmp)はコンテナ再起動の
たびに空になるエフェメラルなストレージのため、起動時にFirestore側の内容を空の
ローカルDBへ書き戻す。これによりFirestoreは「クラウド側が自らデータを生成・改変する
主体にはならない読み取り専用レプリカ/バックアップ」という位置づけを保ったまま
(あくまでローカルSQLiteが正、Firestoreへの書き込みはこのモジュール経由のPush/Pull
のみ)、Cloud Runの再起動を跨いだデータの実効的な永続化を実現する。
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import sys
from typing import Any

import firebase_admin
from firebase_admin import firestore

from .database import (
    AuditLogORM,
    QualityCircuitBreakerStateORM,
    ResearchArticleORM,
    TriggerStateORM,
    async_bulk_restore_items_if_missing,
    async_bulk_restore_rows_if_missing,
    async_get_all_rows,
    get_pending_sync_batch,
    mark_sync_failed,
    mark_synced,
)

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "nazokake_items"

# persona_feature_plan_v3.md §9.3: nazokake_items以外にFirestoreの同期対象へ
# 追加する4テーブル。いずれもCloud Runの/tmpにしかなく、再起動のたびに失われて
# いたため、Push(バックアップ)とPull(起動時復元)の両方を対象にする。
# (collection名, ORM, 主キー列名)。collection名はテーブル名と同一にする
# (nazokake_itemsと同じ命名規約、FIRESTORE_SYNC_COLLECTIONのような個別の
# 環境変数オーバーライドはPhase1では設けない)。
_STRUCTURAL_SYNC_TARGETS: tuple[tuple[str, type, str], ...] = (
    ("audit_logs", AuditLogORM, "id"),
    ("trigger_state", TriggerStateORM, "pipeline_id"),
    ("quality_circuit_breaker_state", QualityCircuitBreakerStateORM, "pipeline_id"),
    ("research_articles", ResearchArticleORM, "article_id"),
)

# instructions/240: 起動時リストアを、一括insert可能な数千件規模でも安全な
# ホストパラメータ数(チャンクサイズ x NazokakeItemORMの列数)に収めるための単位。
_RESTORE_CHUNK_SIZE = 200

# ローカルDB専用のブックキーピングカラムはFirestore側へは送らない。
_LOCAL_ONLY_FIELDS = {"sync_status", "last_sync_error"}

# 【instructions/282】workers/ondemand_elyza_worker.pyが唯一の書き手として直接
# Firestoreへ書き込むと定められた狭いフィールド集合(SSoT §8.2、instructions/250)。
# ローカルSQLite側は、オンデマンドジョブキューへの初回合図("pending")として一度
# しかこれらの値を書かない(以降の状態遷移はワーカーがFirestore側で直接行う)ため、
# ローカル値はワーカーが一度でも更新した後は必ず陳腐化する。既存のmerge=True
# (_push_one_sync参照)は「ローカル行が知らないフィールドを消さない」効果しか
# 持たず、「ローカル行が保持する陳腐化した値でワーカーの最新値を上書きしてしまう」
# ケースまでは防げていなかった(このバグにより、ワーカーがelyza_job_statusを
# "processing"/"completed"へ進めた直後に、Cloud Run側の定期バックアップPushが
# ローカルの古い"pending"で上書きし、フィールドの状態が意図せず巻き戻る/消える
# ことがあった)。_build_push_payload()でリモート側に既に値が存在する場合のみ
# これらのフィールドをpayloadから除外し、ワーカーの書き込みを優先する。
_WORKER_OWNED_ELYZA_JOB_FIELDS = {
    "elyza_job_status",
    "elyza_job_locked_at",
    "elyza_job_retry_count",
}

# 【本番調査(2026-08-18): ELYZAが常に8秒ACKタイムアウトで代打になる障害】
# elyza_job_statusは_WORKER_OWNED_ELYZA_JOB_FIELDSの中で唯一、ワーカーだけでなく
# Cloud Run自身も書く値("pending"=generate_ai()の初回合図、"cancelled"=
# apps/evaluator/backend/api/routers/generate.py::process_elyza()の8秒ACK
# タイムアウト確定)。_build_push_payload()の「リモートに既に値があればローカルの
# 陳腐化した値で上書きしない」という保護(instructions/282)は、本来ワーカーの
# 進捗(processing/completed/dead_letter)をCloud Runの定期バックアップPushが
# 巻き戻すのを防ぐためのものだが、"pending"→"cancelled"というCloud Run自身の
# 正当な書き込みまで一律に弾いてしまっていた: generate_ai()が最初にpendingを
# Push→8秒後にcancelledへローカル更新してPushし直しても、リモートが既に
# "pending"(値あり)のためこの2回目のPushからelyza_job_statusが除外され、
# Firestore側はpendingのまま永久に取り残される。取り残されたジョブは
# workers/ondemand_elyza_worker.py::_find_claimable_doc_idsのpendingクエリに
# 今後も何度でもヒットし続け、ワーカーの処理枠(CLAIM_BATCH_SIZE)を既に代打済みの
# 無駄なジョブで消費してしまい、新規ジョブが8秒ACK窓に間に合わなくなる
# (本番Firestoreで実際にstatus=all_completed/elyza_job_status=pendingのまま
# 取り残された件数15件を確認、うち10件はllmjp_status=completed=既に代打済み)。
# "pending"はCloud Run自身が書く値でありワーカーの進捗ではないため、リモートが
# まだ"pending"の間はこのフィールドを保護対象から除外してよい(ワーカーが実際に
# claimして"pending"以外へ進めた後にのみ保護を有効化する)。
_ELYZA_JOB_STATUS_UNCLAIMED = "pending"


def _resolve_collection() -> str:
    """環境変数 FIRESTORE_SYNC_COLLECTION で同期先コレクションを上書きできる
    (本番の nazokake_items を汚さずにテスト用コレクションへ向けるため)。"""
    return os.environ.get("FIRESTORE_SYNC_COLLECTION", DEFAULT_COLLECTION)


def _ensure_firebase_app() -> None:
    if not firebase_admin._apps:
        project_id = os.environ.get("GCP_PROJECT_ID") or None
        if project_id:
            firebase_admin.initialize_app(options={"projectId": project_id})
        else:
            firebase_admin.initialize_app()


def _build_push_payload(
    row: dict[str, Any], *, remote_data: dict[str, Any] | None
) -> dict[str, Any]:
    """Cloud Run側の定期バックアップPushのpayloadを組み立てる。

    remote_dataは同一トランザクション内で読んだリモートドキュメントの現在値
    (存在しない場合はNone)。_WORKER_OWNED_ELYZA_JOB_FIELDSのうち、リモート側に
    既に値が設定されているものは、ローカルの陳腐化した値で上書きしないよう
    payloadから除外する(instructions/282)。リモートにまだ存在しない場合
    (ドキュメント新規作成時の初回"pending"合図)は、通常通りローカル値を含める。

    【2026-08-18修正】elyza_job_statusに限っては、リモートの値がまだ"pending"
    (=ワーカーが一度もclaimしておらず、Cloud Run自身が書いた値のまま)の間は
    保護対象から除外しない。これにより8秒ACKタイムアウト時のCloud Run自身の
    "pending"→"cancelled"更新がFirestoreへ正しく反映されるようになる
    (_ELYZA_JOB_STATUS_UNCLAIMEDのコメント参照)。
    """
    payload = {k: v for k, v in row.items() if k not in _LOCAL_ONLY_FIELDS and v is not None}
    if remote_data:
        for field in _WORKER_OWNED_ELYZA_JOB_FIELDS:
            if field not in payload:
                continue
            remote_value = remote_data.get(field)
            if remote_value is None:
                continue
            if field == "elyza_job_status" and remote_value == _ELYZA_JOB_STATUS_UNCLAIMED:
                continue
            del payload[field]
    return payload


def _push_one_sync(db, collection: str, row: dict[str, Any]) -> str:
    """1件をFirestoreへ冪等/順序保護付きでPushする(同期関数、asyncio.to_threadから呼ぶ)。

    Firestore上の既存ドキュメントのupdated_atがローカルのそれより新しい場合は
    「順序逆転」とみなし、上書きせずスキップする。戻り値は "pushed" または
    "skipped_stale"。

    【instructions/250】merge=Trueで書き込む(非merge の set() は、payload に
    含まれないフィールドをすべて削除する全置換のため)。このローカル行が知らない
    フィールド(例: workers/ondemand_elyza_worker.pyがelyza_job_status等の狭い
    フィールド集合にスコープを絞って直接書き込んだ結果)を、Cloud Run側の定期的な
    バックアップPushが誤って消し去ることを防ぐ。skip_staleの判定ロジック自体は
    このmerge化と無関係(判定は書き込みの実行有無のみを左右し、書き込み方式には
    影響しない)。

    【instructions/282】上記のmerge=True保護は「ローカル行が知らないフィールドを
    消さない」効果しか持たず、「ローカル行が持つ(が既に陳腐化した)値でワーカーの
    最新値を上書きしてしまう」ケースは別途_build_push_payload()のremote_data参照で
    防ぐ(このためtransaction内で読んだsnapshotをpayload組み立てに渡す)。
    """
    doc_ref = db.collection(collection).document(row["doc_id"])
    local_updated_at = row.get("updated_at")

    @firestore.transactional
    def _txn(transaction) -> str:
        snapshot = doc_ref.get(transaction=transaction)
        remote_data = None
        if snapshot.exists:
            remote_data = snapshot.to_dict()
            remote_updated_at = snapshot.get("updated_at")
            if (
                remote_updated_at is not None
                and local_updated_at is not None
                and remote_updated_at > local_updated_at
            ):
                return "skipped_stale"
        payload = _build_push_payload(row, remote_data=remote_data)
        transaction.set(doc_ref, payload, merge=True)
        return "pushed"

    return _txn(db.transaction())


def _push_structural_table_sync(
    db, collection: str, pk_column: str, rows: list[dict[str, Any]]
) -> int:
    """1テーブル分を丸ごとFirestoreへUpsertする(同期関数、asyncio.to_threadから呼ぶ)。

    nazokake_itemsの_push_one_syncと異なり、リモートの新旧比較(順序逆転防止)は
    行わない。対象4テーブルはこのモジュールのPush以外にFirestoreへ書き込む主体が
    存在しない(split-brainの懸念がない)ため、単純な上書きで十分(§9.3)。
    """
    pushed = 0
    for row in rows:
        doc_id = str(row[pk_column])
        payload = {k: v for k, v in row.items() if v is not None}
        db.collection(collection).document(doc_id).set(payload, merge=True)
        pushed += 1
    return pushed


async def _push_structural_tables(db) -> dict[str, int]:
    """_STRUCTURAL_SYNC_TARGETSの4テーブルを、それぞれ全件Firestoreへ丸ごとPushする。

    1テーブルのPush失敗が他テーブルや呼び出し元(sync_once)を巻き込まないよう、
    テーブルごとに個別にtry/exceptする。
    """
    stats: dict[str, int] = {}
    for collection, orm_cls, pk_column in _STRUCTURAL_SYNC_TARGETS:
        try:
            rows = await async_get_all_rows(orm_cls)
            pushed = await asyncio.to_thread(
                _push_structural_table_sync, db, collection, pk_column, rows
            )
            stats[collection] = pushed
        except Exception as e:
            sys.stderr.write(
                f"[firestore_sync][structural] {collection} のPushに失敗しました: {e}\n"
            )
            stats[collection] = 0
    return stats


async def sync_once(batch_size: int = 20) -> dict[str, Any]:
    """未同期(pending/error)バッチを1回分処理する。戻り値は件数の集計。

    §9.3: nazokake_itemsの差分Pushに加え、_STRUCTURAL_SYNC_TARGETSの4テーブルも
    毎回全件Pushする(件数が少ないため許容できるコスト)。結果は"structural"キー
    (テーブル名 -> push件数の辞書)にまとめ、既存の"pushed"等のキー(nazokake_items
    向け)とは独立させる(既存呼び出し元のstats.get("pushed", 0)等の参照を壊さない)。
    """
    _ensure_firebase_app()
    db = firestore.client()
    collection = _resolve_collection()

    rows = await get_pending_sync_batch(limit=batch_size)
    stats: dict[str, Any] = {
        "pushed": 0,
        "skipped_stale": 0,
        "failed": 0,
        "fatal": 0,
        "total": len(rows),
    }

    for row in rows:
        doc_id = row["doc_id"]
        try:
            outcome = await asyncio.to_thread(_push_one_sync, db, collection, row)
            await mark_synced(doc_id, row.get("updated_at"))
            stats[outcome] += 1
        except Exception as e:
            sys.stderr.write(
                f"[firestore_sync][DEAD-LETTER] doc_id={doc_id} の同期に失敗しました: {e}\n"
            )
            # "failed" は今回の試行が失敗した件数(次回リトライされ得る"error"含む)、
            # "fatal" はそのうちMAX_SYNC_RETRIES到達でポイズンピル隔離("fatal"、
            # 二度とリトライ対象にならない)された件数のみを数える内数。
            became_fatal = await mark_sync_failed(doc_id, str(e))
            stats["failed"] += 1
            if became_fatal:
                stats["fatal"] += 1

    stats["structural"] = await _push_structural_tables(db)
    return stats


async def sync_once_safe(batch_size: int = 20) -> None:
    """instructions/239: apps/evaluator/backend(Cloud Run)がFastAPIのBackgroundTasks
    経由で呼ぶための安全側ラッパー。BackgroundTasksはHTTPレスポンス送出後に実行される
    ため、ここで例外を外へ伝播させてもユーザーには届かずサーバー側のノイズにしか
    ならない。個々のアイテムの同期失敗はsync_once内部で既にmark_sync_failedにより
    次回リトライ対象として記録されるため、ここで捕捉するのは
    get_pending_sync_batch自体の失敗やFirebase初期化失敗等、sync_onceのループに
    到達する前の例外のみを想定している。
    """
    try:
        await sync_once(batch_size=batch_size)
    except Exception as e:  # noqa: BLE001 - BackgroundTasksの外へ例外を漏らさない意図的な捕捉
        logger.warning(f"⚠️ Firestoreバックアップ同期(BackgroundTasks)に失敗しました: {e}")


def _normalize_for_sqlite(value: Any) -> Any:
    """FirestoreのDatetimeWithNanoseconds(datetime.datetimeのサブクラス)等、
    そのままではSQLite/JSON列へ保存できない型をISO8601文字列へ変換する。
    このコードベース全体の規約(TriggerStateORM等参照)通り、日時はdatetime型
    カラムではなく文字列として保存するため、通常のdatetime.datetimeも同様に
    変換対象とする。

    persona/trend/result等のJSON型カラムはdict/listのネスト構造を持ち、その内部
    にもFirestoreのタイムスタンプ(例: trend.fetched_at)が含まれ得るため、
    再帰的に変換する(実機検証で、トップレベルのみの変換では
    "Object of type DatetimeWithNanoseconds is not JSON serializable"が
    ネスト位置で発生することを確認済み)。
    """
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _normalize_for_sqlite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_for_sqlite(v) for v in value]
    return value


async def _restore_structural_tables(db) -> dict[str, dict[str, int]]:
    """§9.3: _STRUCTURAL_SYNC_TARGETSの4テーブルを、それぞれ丸ごとFirestoreから
    Pull復元する(既存優先、async_bulk_restore_rows_if_missingのINSERT OR IGNORE
    セマンティクス)。nazokake_itemsのような1万件超のチャンク分割は対象4テーブルの
    実測件数(いずれも数十件以下)では不要なため、1テーブル1バッチで復元する。
    """
    stats: dict[str, dict[str, int]] = {}
    for collection, orm_cls, pk_column in _STRUCTURAL_SYNC_TARGETS:
        table_stats = {"restored": 0, "skipped_existing": 0, "skipped_invalid": 0, "errors": 0}
        try:
            docs = await asyncio.to_thread(lambda c=collection: list(db.collection(c).stream()))
            valid_rows: list[dict[str, Any]] = []
            for doc in docs:
                data = doc.to_dict() or {}
                data[pk_column] = doc.id
                if not data.get(pk_column):
                    table_stats["skipped_invalid"] += 1
                    continue
                valid_rows.append({k: _normalize_for_sqlite(v) for k, v in data.items()})

            restored, skipped_existing = await async_bulk_restore_rows_if_missing(
                orm_cls, pk_column, valid_rows
            )
            table_stats["restored"] = restored
            table_stats["skipped_existing"] = skipped_existing
        except Exception as e:
            logger.warning(
                f"⚠️ [firestore_restore][structural] {collection} の復元に失敗しました: {e}"
            )
            table_stats["errors"] += 1
        stats[collection] = table_stats
    return stats


async def async_restore_from_firestore() -> dict[str, Any]:
    """instructions/240: Cloud Run起動時、空のローカルSQLiteへFirestoreの
    nazokake_itemsコレクションから全件をPull(復元)する。sync_once()と対になる
    復元方向の処理で、これによりPush/Pull両方向が揃い「Cloud Run再起動でSQLiteが
    空になり、アプリ上のデータが消える」問題を解消する。

    【nazokake_core.schemas.NazokakeItemを使わない理由】そのスキーマは
    extra="forbid"かつ多数のフィールド(id/result/source/model_id/
    evaluator_model_id/persona/trend等)が必須で、apps/batch_factoryが完全な形で
    書き込むアイテムを前提としている。一方、今回実際に復元したいデータの大半は
    instructions/239でバックアップ対象にしたapps/evaluator/backend(Cloud Run)
    自身が書く部分行(id/persona/trend等を含まず、result_geminiはあってもresultは
    無い等)であり、NazokakeItemORM側では元々これらの列はNULL許容(doc_id/odai
    以外)。厳格なNazokakeItemで検証すると、復元したい対象のほぼ全件がバリデー
    ションエラーで復元されずに終わってしまうため、実際のDB制約
    (doc_id/odaiのみ必須)に沿った最小限の検証のみ行う。

    【一括処理(実機検証で判明)】このコレクションは実測1万件超(過去のアーキテクチャ
    世代由来と見られるodai欠落の不正行が大半を占める)。1件ずつsession.get()で
    存在確認してから個別commitする素朴な実装では起動が数分単位でブロックされ、
    Cloud Runの起動タイムアウトに抵触しかねないため、database.pyの
    async_bulk_restore_items_if_missing()でチャンク単位の一括insertを行う。
    """
    _ensure_firebase_app()
    db = firestore.client()
    collection = _resolve_collection()

    stats: dict[str, Any] = {
        "restored": 0,
        "skipped_existing": 0,
        "skipped_invalid": 0,
        "errors": 0,
    }

    docs = await asyncio.to_thread(lambda: list(db.collection(collection).stream()))

    valid_rows: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        data["doc_id"] = doc.id
        if not data.get("odai"):
            stats["skipped_invalid"] += 1
            continue
        valid_rows.append({k: _normalize_for_sqlite(v) for k, v in data.items()})

    for i in range(0, len(valid_rows), _RESTORE_CHUNK_SIZE):
        chunk = valid_rows[i : i + _RESTORE_CHUNK_SIZE]
        try:
            restored, skipped_existing = await async_bulk_restore_items_if_missing(chunk)
            stats["restored"] += restored
            stats["skipped_existing"] += skipped_existing
        except Exception as e:
            logger.warning(
                f"⚠️ [firestore_restore] チャンク(先頭doc_id={chunk[0].get('doc_id')})の"
                f"復元に失敗しました: {e}"
            )
            stats["errors"] += len(chunk)

    logger.info(
        f"🔄 [firestore_restore] restored={stats['restored']} "
        f"skipped_existing={stats['skipped_existing']} "
        f"skipped_invalid={stats['skipped_invalid']} errors={stats['errors']}"
    )

    structural_stats = await _restore_structural_tables(db)
    stats["structural"] = structural_stats
    logger.info(f"🔄 [firestore_restore][structural] {structural_stats}")

    return stats

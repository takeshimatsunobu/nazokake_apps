"""data-sync-daemon の起動エントリポイント(instructions/003)。

Firestoreの aufheben_events コレクション(本番Cloud Runで収集された、SNS上の
不毛な争いをユーモアでアウフヘーベンさせた成否データ。SSoT_architecture.md 9節の
「ビジネスロジックのフロー」参照)から、ローカルSQLite(/data/sqlite/flywheel.db、
データフライホイールのSSoT)へ一方向でPull同期する。ローカルへ還流したデータは
agent-workspace側の継続的自己改善(プロンプト評価・DPO/SFTデータ蓄積)のトリガーとなる。

packages/shared_core/nazokake_core/firestore_sync.py (ローカル→Firestoreの
Push方向、nazokake_itemsコレクション)とは逆方向・別コレクションの同期であり、
意図的に別モジュールとして実装する(役割が異なるため、無理な共通化はしない)。
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time

import firebase_admin
from firebase_admin import credentials, firestore

DB_PATH = "/data/sqlite/flywheel.db"
CREDENTIALS_DIR = "/data/credentials"
FIRESTORE_COLLECTION = os.environ.get("AUFHEBEN_EVENTS_COLLECTION", "aufheben_events")

EPOCH_DEFAULT = "1970-01-01T00:00:00Z"

POLL_INTERVAL_SECONDS = 300
INITIAL_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 300


def _log(message: str) -> None:
    print(f"[sync_daemon] {message}", file=sys.stderr, flush=True)


def _connect_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    # agent-workspace等との並行アクセスにおけるロック競合を防止する
    # (instructions/003要件)。
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sync_metadata ("
        "id INTEGER PRIMARY KEY, last_synced_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS aufheben_events ("
        "event_id TEXT PRIMARY KEY, riddle_id TEXT, context_text TEXT, "
        "aufheben_status INTEGER, created_at TEXT)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO sync_metadata (id, last_synced_at) VALUES (1, ?)",
        (EPOCH_DEFAULT,),
    )
    conn.commit()


def _get_last_synced_at(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT last_synced_at FROM sync_metadata WHERE id = 1"
    ).fetchone()
    if row is None or row[0] is None:
        return EPOCH_DEFAULT
    return row[0]


def _find_credentials_file() -> "credentials.Certificate | None":
    if not os.path.isdir(CREDENTIALS_DIR):
        return None
    for name in sorted(os.listdir(CREDENTIALS_DIR)):
        if name.endswith(".json"):
            return credentials.Certificate(os.path.join(CREDENTIALS_DIR, name))
    return None


def _ensure_firebase_app() -> None:
    if firebase_admin._apps:
        return
    project_id = os.environ.get("GCP_PROJECT_ID") or None
    options = {"projectId": project_id} if project_id else None
    cred_obj = _find_credentials_file()
    if cred_obj is not None:
        _log(f"{CREDENTIALS_DIR} 配下のサービスアカウントキーでFirebase Appを初期化します。")
        firebase_admin.initialize_app(cred_obj, options=options)
    else:
        # 鍵ファイルが無い場合はGOOGLE_APPLICATION_CREDENTIALS等の環境変数
        # (Application Default Credentials)にフォールバックする。
        _log("鍵ファイル未検出のため、Application Default Credentialsで初期化します。")
        firebase_admin.initialize_app(options=options)


def _fetch_new_events(last_synced_at: str) -> list[dict]:
    db = firestore.client()
    # created_at > last_synced_at の範囲クエリ + 同一フィールドのorder_byは
    # Firestoreの単一フィールド索引で解決でき、複合索引は不要。
    query = (
        db.collection(FIRESTORE_COLLECTION)
        .where("created_at", ">", last_synced_at)
        .order_by("created_at")
    )
    events: list[dict] = []
    for doc in query.stream():
        data = doc.to_dict() or {}
        created_at = data.get("created_at")
        if not created_at:
            # created_atが欠損したドキュメントは同期対象から除外する
            # (last_synced_atの単調増加が壊れ、無限リトライループになるため)。
            _log(f"created_at欠損のためスキップします: doc_id={doc.id}")
            continue
        events.append(
            {
                "event_id": doc.id,
                "riddle_id": data.get("riddle_id"),
                "context_text": data.get("context_text"),
                "aufheben_status": data.get("aufheben_status"),
                "created_at": created_at,
            }
        )
    return events


def _apply_events(conn: sqlite3.Connection, events: list[dict]) -> str:
    rows = [
        (
            e["event_id"],
            e["riddle_id"],
            e["context_text"],
            e["aufheben_status"],
            e["created_at"],
        )
        for e in events
    ]
    new_last_synced_at = max(e["created_at"] for e in events)
    # INSERT OR REPLACEによる書き込みとsync_metadataの更新を同一トランザクション
    # (`with conn:`はsqlite3のBEGIN...COMMIT/ROLLBACKを自動化する)でコミットし、
    # 途中失敗時に「イベントは書けたがlast_synced_atが進んでいない」半端な状態を防ぐ
    # (instructions/003の「アトミックトランザクション」要件)。
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO aufheben_events "
            "(event_id, riddle_id, context_text, aufheben_status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute(
            "UPDATE sync_metadata SET last_synced_at = ? WHERE id = 1",
            (new_last_synced_at,),
        )
    return new_last_synced_at


def _sync_once(conn: sqlite3.Connection) -> None:
    _ensure_firebase_app()
    last_synced_at = _get_last_synced_at(conn)
    events = _fetch_new_events(last_synced_at)
    if not events:
        _log(f"新規イベントはありません(last_synced_at={last_synced_at})。")
        return
    new_last_synced_at = _apply_events(conn, events)
    _log(f"{len(events)}件のaufheben_eventsを同期しました(last_synced_at={new_last_synced_at})。")


def main() -> None:
    conn = _connect_db()
    _init_schema(conn)

    backoff = INITIAL_BACKOFF_SECONDS
    while True:
        try:
            _sync_once(conn)
            backoff = INITIAL_BACKOFF_SECONDS
            time.sleep(POLL_INTERVAL_SECONDS)
        except Exception as exc:  # 通信エラー・GCP API制限(429/503等)を含む全異常系
            _log(
                f"同期に失敗しました({type(exc).__name__}: {exc})。"
                f"{backoff}秒後に再試行します。"
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)


if __name__ == "__main__":
    main()

"""一時診断スクリプト: nazokake_items 生データ解剖（SSL検証オフ版）。
企業プロキシ等によるSSLインターセプト環境での最終手段。
実行後は削除してください。
"""

import os
import sys
import warnings

warnings.filterwarnings("ignore")  # SSL警告を抑制

os.environ["PYTHONHTTPSVERIFY"] = "0"

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import ssl

ssl._create_default_https_context = ssl._create_unverified_context

import urllib3

urllib3.disable_warnings()

import requests

# SSL検証を無効にしたセッション
_session = requests.Session()
_session.verify = False

from pathlib import Path
from google.oauth2 import service_account
import google.auth.transport.requests

PROJECT_ID = "nazokakeapp-137e5"
DATABASE = "(default)"
COLLECTION = "nazokake_items"
SCRIPT_DIR = Path(__file__).resolve().parent
KEY_PATH = SCRIPT_DIR.parent.parent / "serviceAccountKey.json"
SCOPES = ["https://www.googleapis.com/auth/datastore"]
BASE_URL = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/{DATABASE}/documents"

print(f"serviceAccountKey: {KEY_PATH}  exists={KEY_PATH.exists()}")

# SSL検証オフのトランスポートでトークン取得
creds = service_account.Credentials.from_service_account_file(
    str(KEY_PATH), scopes=SCOPES
)
auth_req = google.auth.transport.requests.Request(session=_session)
creds.refresh(auth_req)
headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
print("✅ アクセストークン取得成功")

SEP = "-" * 70


def fs_value(v):
    if not isinstance(v, dict):
        return v
    if "stringValue" in v:
        return str(v["stringValue"])
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "booleanValue" in v:
        return bool(v["booleanValue"])
    if "nullValue" in v:
        return None
    if "timestampValue" in v:
        return v["timestampValue"]
    if "mapValue" in v:
        return {k2: fs_value(v2) for k2, v2 in v["mapValue"].get("fields", {}).items()}
    if "arrayValue" in v:
        return [fs_value(item) for item in v["arrayValue"].get("values", [])]
    return v


def parse_doc(doc):
    doc_id = doc.get("name", "").split("/")[-1]
    fields = {k: fs_value(v) for k, v in doc.get("fields", {}).items()}
    return doc_id, fields


def run_query(structured_query):
    url = f"{BASE_URL}:runQuery"
    resp = _session.post(
        url, headers=headers, json={"structuredQuery": structured_query}, timeout=30
    )
    resp.raise_for_status()
    return [item["document"] for item in resp.json() if "document" in item]


# ── 1. status==2 (整数) ─────────────────────────────────────────────
print(SEP)
print("■ QUERY A: status == 2 (整数)")
docs_int = run_query(
    {
        "from": [{"collectionId": COLLECTION}],
        "where": {
            "fieldFilter": {
                "field": {"fieldPath": "status"},
                "op": "EQUAL",
                "value": {"integerValue": 2},
            }
        },
        "limit": 500,
    }
)
print(f"  → ヒット件数（上限500）: {len(docs_int)} 件")

# ── 2. status=="all_completed" (文字列) ─────────────────────────────
print(SEP)
print("■ QUERY B: status == 'all_completed' (文字列, 上限500)")
docs_str = run_query(
    {
        "from": [{"collectionId": COLLECTION}],
        "where": {
            "fieldFilter": {
                "field": {"fieldPath": "status"},
                "op": "EQUAL",
                "value": {"stringValue": "all_completed"},
            }
        },
        "limit": 500,
    }
)
print(f"  → ヒット件数（上限500）: {len(docs_str)} 件")

# ── 3. 最新15件の生データ解剖 ──────────────────────────────────────────
print(SEP)
print("■ 最新15件（status='all_completed', created_at 降順）")
try:
    recent_raw = run_query(
        {
            "from": [{"collectionId": COLLECTION}],
            "where": {
                "fieldFilter": {
                    "field": {"fieldPath": "status"},
                    "op": "EQUAL",
                    "value": {"stringValue": "all_completed"},
                }
            },
            "orderBy": [
                {"field": {"fieldPath": "created_at"}, "direction": "DESCENDING"}
            ],
            "limit": 15,
        }
    )
    print(f"  取得件数: {len(recent_raw)} 件")
except Exception as e:
    print(f"  order_by NG ({e})、先頭15件フォールバック")
    recent_raw = docs_str[:15]

recent = [parse_doc(d) for d in recent_raw]

for i, (doc_id, d) in enumerate(recent, 1):
    all_keys = sorted(d.keys())
    relevant = {
        k: v
        for k, v in d.items()
        if any(
            p in k.lower()
            for p in (
                "s_total",
                "score",
                "result",
                "status",
                "eval_status",
                "llmjp_status",
                "source",
                "feed_ready",
                "is_golden",
                "is_approved",
            )
        )
    }
    print(f"\n[{i}] doc.id = {doc_id}")
    print(f"  全キー({len(all_keys)}): {all_keys}")
    print("  スコア/結果/ステータス系:")
    for k in sorted(relevant):
        print(
            f"    {k!r:42s} = {repr(relevant[k])[:120]}  (type={type(relevant[k]).__name__})"
        )

# ── 4. s_total 系の分布 ───────────────────────────────────────────────
print(SEP)
print("■ s_total 系フィールドの型・値分布（最新15件）")
for doc_id, d in recent:
    s_fields = {k: v for k, v in d.items() if k.startswith("s_total")}
    if s_fields:
        for k, v in sorted(s_fields.items()):
            print(f"  {doc_id[:14]}  {k!r:28s}  {repr(v):12s}  {type(v).__name__}")
    else:
        print(f"  {doc_id[:14]}  s_total系なし  全キー={all_keys[:6]}...")

# ── 5. ステータス行一覧 ────────────────────────────────────────────────
print(SEP)
print("■ ステータス・source・s_total 一覧（最新15件）")
for doc_id, d in recent:
    print(
        f"  {doc_id[:14]}"
        f"  status={repr(d.get('status', '?')):25s}"
        f"  eval={repr(d.get('eval_status', '?')):15s}"
        f"  src={repr(d.get('source', '-')):25s}"
        f"  s_total={repr(d.get('s_total', '?'))}"
    )

print(SEP)
print("診断完了")

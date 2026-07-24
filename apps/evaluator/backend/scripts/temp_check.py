"""一時診断: board_posts の実フィールド状態を5件サンプリング（Read-Only）。
カテゴリ分割クエリ（category == 'nazokake'）から既存データが漏れる原因の確認用。
実行後は不要なら削除してよい使い捨てスクリプト。
"""

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# 本番(main.py)と同じ方式でプロジェクトIDを確定させる
import firebase_admin
from firebase_admin import firestore as admin_firestore

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})

db = admin_firestore.client()

print("=== Firestore board_posts Data Sample (max 5) ===")
count = 0
for doc in db.collection("board_posts").limit(5).stream():
    count += 1
    d = doc.to_dict() or {}
    print(f"ID: {doc.id}")
    print(f"  - category   : {d.get('category', 'MISSING!')}")
    print(f"  - parent_id  : {d.get('parent_id', 'MISSING!')}")
    print(f"  - created_at : {type(d.get('created_at'))} (Exists: {'created_at' in d})")
    print(f"  - all_keys   : {sorted(d.keys())}")

print(f"=== sampled {count} document(s) ===")

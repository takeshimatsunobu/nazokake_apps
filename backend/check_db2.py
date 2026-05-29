import firebase_admin
from firebase_admin import firestore
import json

if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.client()
# 💡 古い created_at ではなく、本番の timestamp で最新1件を取得
docs = db.collection("nazokake_items").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(1).stream()

for doc in docs:
    print(f"=== 最新ドキュメント (ID: {doc.id}) ===")
    data = doc.to_dict()
    # Firestoreの日時オブジェクトを文字列に変換して綺麗に出力
    print(json.dumps(data, indent=2, default=str, ensure_ascii=False))

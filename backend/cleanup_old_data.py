import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import os

# 発行したばかりの鍵ファイルを指定
key_file_path = "nazokakeapp-137e5-firebase-adminsdk-fbsvc-8fec1ba420.json"

print(f"🔑 鍵ファイルを使用します: {key_file_path}")

try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(key_file_path)
        firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"🚨 Firebaseの初期化に失敗しました。鍵ファイルが backend フォルダ内に置かれているか確認してください。\n詳細なエラー: {e}")
    exit()

db = firestore.client()
collection_name = "nazokake_items"

print("🔍 スコアを持たない古いデータを検索中...")
docs = db.collection(collection_name).stream()

deleted_count = 0
for doc in docs:
    data = doc.to_dict()
    # 'scores' という項目が存在しない、または空のドキュメントを特定して削除
    if 'scores' not in data or not data['scores']:
        print(f"🗑️ 削除中: [{doc.id}] {data.get('A_TITLE', 'タイトル不明')}")
        db.collection(collection_name).document(doc.id).delete()
        deleted_count += 1

print(f"✅ 完了！合計 {deleted_count} 件の古い未評価データを一掃しました。")

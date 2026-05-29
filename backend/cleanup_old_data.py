import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# 発行したばかりの鍵ファイルを指定
KEY_FILE_PATH = "nazokakeapp-137e5-firebase-adminsdk-fbsvc-8fec1ba420.json"
COLLECTION_NAME = "nazokake_items"

try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(KEY_FILE_PATH)
        firebase_admin.initialize_app(cred)
except Exception as e:
    # 初期化失敗時は処理を停止
    raise RuntimeError(f"Firebaseの初期化に失敗しました。鍵ファイルが正しいか確認してください。エラー: {e}")

db = firestore.client()

deleted_count = 0
print(f"--- 古い未評価データの削除処理を開始します ({COLLECTION_NAME}) ---")

# 全ドキュメントをストリームで取得
docs = db.collection(COLLECTION_NAME).stream()

# 削除対象のIDを収集し、処理を効率化する
ids_to_delete = []
for doc in docs:
    data = doc.to_dict()
    # 'scores' が存在しない、または空のリスト/Noneの場合に削除対象とする
    if 'scores' not in data or not data['scores']:
        ids_to_delete.append(doc.id)

# 収集したIDをまとめて削除
if ids_to_delete:
    print(f"検出された削除対象データ数: {len(ids_to_delete)} 件")
    for doc_id in ids_to_delete:
        try:
            db.collection(COLLECTION_NAME).document(doc_id).delete()
            deleted_count += 1
        except Exception as e:
            print(f"警告: ドキュメント {doc_id} の削除に失敗しました。エラー: {e}")
else:
    print("削除対象のデータは見つかりませんでした。")

print(f"--- 処理完了。合計 {deleted_count} 件の古い未評価データを削除しました。 ---")
import os
import firebase_admin
from firebase_admin import credentials, firestore

# プロジェクトルート（nazokake-evaluator）から実行されることを前提とした鍵のパス
CRED_PATH = "backend/serviceAccountKey.json"

if not os.path.exists(CRED_PATH):
    print(f"❌ 鍵ファイルが見つかりません: {CRED_PATH}")
    print("実行場所が間違っている可能性があります。プロジェクトルートから実行してください。")
    exit(1)

# Firestoreの初期化
cred = credentials.Certificate(CRED_PATH)
firebase_admin.initialize_app(cred)
db = firestore.client()

def cleanup_ghosts():
    print("🔍 データベースのゴースト（旧ステータスデータ）をスキャン中...")
    
    # コレクション内の全ドキュメントを取得
    docs = db.collection("nazokake_items").stream()
    count = 0

    for d in docs:
        data = d.to_dict()
        status = data.get("status")

        # ★ゴーストの判定ロジック: 数値(int)のステータスはすべて削除
        if isinstance(status, int):
            odai = data.get('A_TITLE', '不明なお題')
            print(f"👻 ゴースト発見 [ID: {d.id}] - Status: {status} / お題: {odai}")
            
            # データベースからドキュメントを物理削除
            db.collection("nazokake_items").document(d.id).delete()
            print("   ➔ 🧹 除霊（削除）完了！")
            count += 1

    print("-" * 40)
    if count == 0:
        print("✨ ゴーストは見つかりませんでした。データベースは完全にクリーンです！")
    else:
        print(f"✅ 合計 {count} 体のゴーストを成仏させました。")

if __name__ == "__main__":
    cleanup_ghosts()
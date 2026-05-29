import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path

def fix_schema():
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 timestamp が欠損しているデータを捜索し、修正します...")
    docs = db.collection("nazokake_items").stream()
    
    count = 0
    for doc in docs:
        data = doc.to_dict()
        
        # timestampが存在しないデータのみをターゲットにする
        if "timestamp" not in data:
            title = data.get("A_TITLE", "不明")
            doc_ref = db.collection("nazokake_items").document(doc.id)
            
            # 正しいキー「timestamp」に、Firestoreのタイムスタンプ型をセット
            doc_ref.update({
                "timestamp": firestore.SERVER_TIMESTAMP
            })
            
            count += 1
            print(f"✅ お題「{title}」に timestamp を付与しました！")
            
    if count == 0:
        print("⚠️ 修正が必要なデータは見つかりませんでした。")
    else:
        print(f"🎉 計 {count} 件のデータ修正が完了しました！ブラウザをリロードしてください。")

if __name__ == "__main__":
    fix_schema()

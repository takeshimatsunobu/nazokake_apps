import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path

def fix_schema_to_timestamp():
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 Takeshi_Gemini_Brainstorm のデータを捜索し、timestamp を付与します...")
    try:
        docs = db.collection("nazokake_items").where("author", "==", "Takeshi_Gemini_Brainstorm").stream()
        
        count = 0
        for doc in docs:
            count += 1
            data = doc.to_dict()
            title = data.get("A_TITLE", "不明")
            
            # 正しいキー「timestamp」に、Firestoreの公式タイムスタンプ型をセット
            # ついでに不要な「created_at」を削除して掃除
            doc_ref = db.collection("nazokake_items").document(doc.id)
            doc_ref.update({
                "timestamp": firestore.SERVER_TIMESTAMP,
                "created_at": firestore.DELETE_FIELD
            })
            
            print(f"✅ お題「{title}」に timestamp を付与しました！")
            
        if count == 0:
            print("⚠️ 対象データが見つかりませんでした。")
        else:
            print("🎉 全件のスキーマ修正が完了しました！ブラウザをリロードしてください。")
            
    except Exception as e:
        print(f"🚨 エラー発生: {e}")

if __name__ == "__main__":
    fix_schema_to_timestamp()

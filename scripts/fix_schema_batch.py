import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path

def fix_schema_batch():
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 Takeshi_Gemini_Brainstorm のデータを検索し、メモリに取得します...")
    
    # 🚨 修正1: ターゲットを絞り、全件スキャンによるタイムアウトを回避
    # list() で囲むことで、ストリームを即座に閉じてメモリに確保する
    query = db.collection("nazokake_items").where("author", "==", "Takeshi_Gemini_Brainstorm")
    docs = list(query.stream())
    
    if not docs:
        print("⚠️ 対象データが見つかりませんでした。")
        return
        
    print(f"📦 {len(docs)} 件のデータを発見。バッチ処理で一気に修正します...")
    
    # 🚨 修正2: バッチ（一括書き込み）の準備
    batch = db.batch()
    count = 0
    
    for doc in docs:
        data = doc.to_dict()
        if "timestamp" not in data:
            title = data.get("A_TITLE", "不明")
            doc_ref = db.collection("nazokake_items").document(doc.id)
            
            # バッチに更新予約を追加
            batch.update(doc_ref, {"timestamp": firestore.SERVER_TIMESTAMP})
            count += 1
            print(f"✅ お題「{title}」をバッチの修正キューに追加しました")
            
    if count > 0:
        # 溜め込んだ更新予約を、一回の通信でドカンと反映！
        batch.commit()
        print(f"\n🎉 計 {count} 件のデータ修正をFirestoreにコミットしました！ブラウザをリロードしてください。")
    else:
        print("\n⚠️ すべてのデータは既に timestamp を持っています。")

if __name__ == "__main__":
    fix_schema_batch()

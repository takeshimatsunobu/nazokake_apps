import time
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
# 💡 テストで成功した Vector クラスをこちらにも導入！
from google.cloud.firestore_v1.vector import Vector
from sentence_transformers import SentenceTransformer

def seed_rag_database_glucose_v4():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🚀 国産AI（GLuCoSE v2）をロード中...")
    model = SentenceTransformer('pkshatech/GLuCoSE-base-ja-v2', trust_remote_code=True)

    print("🔍 Firestoreから全データ（status: 2）を取得中...")
    docs = db.collection("nazokake_items").where(filter=FieldFilter("status", "==", 2)).stream()

    items_to_insert = []
    for doc in docs:
        data = doc.to_dict()
        odai = data.get("A_TITLE")
        nazokake = data.get("nazokake_text")
        
        if odai and nazokake:
            items_to_insert.append({
                "id": doc.id,
                "odai": odai,
                "nazokake": nazokake
            })

    total_count = len(items_to_insert)
    print(f"✅ 合計 {total_count} 件のデータを取得しました。")
    if total_count == 0:
        return

    odai_list = [item["odai"] for item in items_to_insert]

    print(f"🧠 {total_count}件のお題をベクトル化中... (PCのパワーを使います)")
    embeddings = model.encode(odai_list, show_progress_bar=True)
    
    print("\n✅ 解析完了。Firestoreへの【Vector型での上書き保存】を開始します...")
    collection_ref = db.collection("nazokake_rag_knowledge")
    
    batch = db.batch()
    batch_count = 0
    total_inserted = 0

    for i, item in enumerate(items_to_insert):
        embedding_list = embeddings[i].tolist()
        
        try:
            doc_ref = collection_ref.document(item["id"])
            batch.set(doc_ref, {
                "odai": item["odai"],
                "nazokake": item["nazokake"],
                # 💡 決定的な修正：純粋なリストを Vector() で包んで保存する！
                "embedding": Vector(embedding_list)
            })
            
            batch_count += 1
            total_inserted += 1
            
            if batch_count >= 50:
                batch.commit()
                print(f"  ... {total_inserted} / {total_count} 件 上書き完了")
                batch = db.batch()
                batch_count = 0
                
        except Exception as e:
             print(f"⚠️ 保存エラー (お題: {item['odai']}): {e}")

    if batch_count > 0:
        batch.commit()
        print(f"  ... {total_inserted} / {total_count} 件 上書き完了")

    print(f"🎉 完璧です！真のVector型によるRAGデータベースの完成です！")

if __name__ == "__main__":
    seed_rag_database_glucose_v4()

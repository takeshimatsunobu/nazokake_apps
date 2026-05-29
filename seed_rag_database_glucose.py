import time
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
# 💡 国産・日本語特化のGLuCoSEモデルを使用
from sentence_transformers import SentenceTransformer

def seed_rag_database_glucose():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🚀 国産AI（GLuCoSE）をロード中...")
    model = SentenceTransformer('pkshatech/GLuCoSE-base-ja')

    print("🔍 Firestoreから全データ（status: 2）を取得中...")
    # 警告を出さずに安全に約9300件を取得
    docs = db.collection("nazokake_items").where(filter=FieldFilter("status", "==", 2)).stream()

    items_to_insert = []
    for doc in docs:
        data = doc.to_dict()
        odai = data.get("A_TITLE")
        nazokake = data.get("nazokake_text")
        
        if odai and nazokake:
            items_to_insert.append({
                "id": doc.id,         # 元のIDを保持しておく
                "odai": odai,
                "nazokake": nazokake
            })

    total_count = len(items_to_insert)
    print(f"✅ 合計 {total_count} 件のデータを取得しました。")
    
    if total_count == 0:
        print("🚨 データが見つかりませんでした。")
        return

    # お題だけを抽出して一気にベクトル化するリストを作成
    odai_list = [item["odai"] for item in items_to_insert]

    print(f"🧠 {total_count}件のお題をベクトル化中... (PCのパワーを使います。数分お待ちください)")
    # show_progress_bar=True で進捗ゲージを表示
    embeddings = model.encode(odai_list, show_progress_bar=True)
    
    print("\n✅ 解析完了。Firestoreへの一括保存を開始します...")
    collection_ref = db.collection("nazokake_rag_knowledge")
    
    batch = db.batch()
    batch_count = 0
    total_inserted = 0

    for i, item in enumerate(items_to_insert):
        # numpy配列をPythonのリストに変換
        embedding_list = embeddings[i].tolist()
        
        try:
            # 元のドキュメントIDと同じIDで保存する（後で紐付けやすくするため）
            doc_ref = collection_ref.document(item["id"])
            batch.set(doc_ref, {
                "odai": item["odai"],
                "nazokake": item["nazokake"],
                "embedding": embedding_list
            })
            
            batch_count += 1
            total_inserted += 1
            
            # 400件ごとにコミット（Firestoreの制限対応）
            if batch_count >= 400:
                batch.commit()
                print(f"  ... {total_inserted} / {total_count} 件登録完了")
                batch = db.batch()
                batch_count = 0
                
        except Exception as e:
             print(f"⚠️ 保存エラー (お題: {item['odai']}): {e}")

    # 残りのバッチをコミット
    if batch_count > 0:
        batch.commit()
        print(f"  ... {total_inserted} / {total_count} 件登録完了")

    print(f"🎉 完璧です！全 {total_inserted} 件の国産AIベースRAGデータベース構築が完了しました！")

if __name__ == "__main__":
    seed_rag_database_glucose()

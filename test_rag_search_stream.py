from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from sentence_transformers import SentenceTransformer

def test_rag_search(search_query="運動会"):
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()

    print("🚀 モデルをロード中...")
    model = SentenceTransformer('pkshatech/GLuCoSE-base-ja-v2', trust_remote_code=True)

    print(f"🔍 お題「{search_query}」をベクトル化中...")
    query_vector = model.encode([search_query])[0].tolist()

    print("📚 Firestoreの9,300件から『似ているお題』を検索中...")
    collection_ref = db.collection("nazokake_rag_knowledge")
    
    try:
        # 💡 修正ポイント: .get() ではなく .stream() を使用する
        results = collection_ref.find_nearest(
            vector_field="embedding",
            query_vector=Vector(query_vector),
            distance_measure=DistanceMeasure.COSINE,
            limit=3
        ).stream()

        count = 0
        print("\n✨ 検索結果 トップ3 ✨")
        for doc in results:
            data = doc.to_dict()
            count += 1
            print(f"第{count}位： お題「{data.get('odai')}」")
            print(f"{data.get('nazokake')}")
            print("-" * 40)
            
        if count == 0:
             print("🚨 検索結果が0件でした。")
            
    except Exception as e:
        print(f"\n🚨 検索エラーが発生しました:\n{e}")

if __name__ == "__main__":
    test_rag_search("運動会")

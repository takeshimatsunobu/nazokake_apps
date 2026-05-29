import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

# プロジェクトルートからの相対パス
CRED_PATH = "backend/serviceAccountKey.json"
SEED_PATH = "data/golden_seeds.json"

if not os.path.exists(CRED_PATH):
    print(f"❌ 鍵ファイルが見つかりません: {CRED_PATH}")
    exit(1)

if not os.path.exists(SEED_PATH):
    print(f"❌ シードファイルが見つかりません: {SEED_PATH}")
    exit(1)

# Firestoreの初期化
if not firebase_admin._apps:
    cred = credentials.Certificate(CRED_PATH)
    firebase_admin.initialize_app(cred)
db = firestore.client()

def inject_seeds():
    print("🌱 ゴールデンデータ（シード）の注入を開始します...")
    
    with open(SEED_PATH, "r", encoding="utf-8") as f:
        seeds = json.load(f)

    count = 0
    for seed in seeds:
        doc_id = seed.get("id")
        
        # 既存のデータがあれば上書き、なければ新規作成
        doc_ref = db.collection("nazokake_items").document(doc_id)
        
        # ステータスは完了状態とし、is_goldenフラグを立てる
        seed_data = {
            "A_TITLE": seed.get("A_TITLE"),
            "nazokake_text": seed.get("nazokake_text"),
            "reasoning": seed.get("reasoning"),
            "is_golden": seed.get("is_golden", True),
            "archetype": seed.get("archetype"),
            "status": "completed"
        }
        
        doc_ref.set(seed_data)
        print(f"✅ 注入完了: [{doc_id}] {seed.get('archetype')}")
        count += 1

    print("-" * 40)
    print(f"🎉 合計 {count} 件のゴールデンデータをFirestoreにデプロイしました！")

if __name__ == "__main__":
    inject_seeds()

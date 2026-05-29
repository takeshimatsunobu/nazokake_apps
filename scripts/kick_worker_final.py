import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path
import requests
import time

# 正しいエンドポイント（/api/evaluate）を指定
EVALUATE_URL = "https://nazokake-backend-862686676938.asia-northeast1.run.app/api/evaluate"

def trigger_worker_manually():
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 評価待ち (status: 0) の注入作品を捜索し、JSONデータで評価APIを叩きます...")
    try:
        docs = db.collection("nazokake_items").where("author", "==", "Takeshi_Gemini_Brainstorm").stream()
        
        found = False
        for doc in docs:
            data = doc.to_dict()
            if data.get("status") != 0:
                continue
                
            found = True
            doc_id = doc.id
            title = data.get("A_TITLE", "不明")
            
            print(f"\n📌 お題: {title} (ID: {doc_id})")
            print(f"🚀 正確なJSONデータ {{'doc_id': '{doc_id}', 'user_score': 0}} を発射...")
            
            # FastAPIが要求する完璧なJSONペイロード
            payload = {
                "doc_id": doc_id,
                "user_score": 0
            }
            
            res = requests.post(EVALUATE_URL, json=payload, timeout=60)
            print(f"📡 API応答コード: {res.status_code}")
            
            if res.status_code == 200:
                print("✅ 評価リクエスト正常受理！ (バックエンドでGeminiが11軸評価中...)")
            else:
                print(f"⚠️ エラー詳細: {res.text[:300]}")
                
            time.sleep(5) # API制限を考慮して5秒待機
            
        if not found:
            print("⚠️ 該当する未評価データが見つかりませんでした。すでに評価済みかもしれません。")
            
    except Exception as e:
        print(f"🚨 エラー発生: {e}")

if __name__ == "__main__":
    trigger_worker_manually()

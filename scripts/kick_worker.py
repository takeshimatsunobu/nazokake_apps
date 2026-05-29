import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path
import requests
import time

WORKER_URL = "https://nazokake-worker-862686676938.asia-northeast1.run.app"
PROJECT_ID = "nazokakeapp-137e5"

def trigger_worker_manually():
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 評価待ち (status: 0) の注入作品を捜索し、ワーカーを強制起動します...")
    try:
        # 複合インデックスエラーを避けるため、まずは著者で全取得
        docs = db.collection("nazokake_items").where("author", "==", "Takeshi_Gemini_Brainstorm").stream()
        
        found = False
        for doc in docs:
            data = doc.to_dict()
            # Python側で status: 0 だけを抽出
            if data.get("status") != 0:
                continue
                
            found = True
            doc_id = doc.id
            title = data.get("A_TITLE", "不明")
            
            print(f"\n📌 お題: {title} (ID: {doc_id})")
            print("🚀 ワーカー強制キック信号を発射...")
            
            headers = {
                "ce-subject": f"projects/{PROJECT_ID}/databases/(default)/documents/nazokake_items/{doc_id}"
            }
            
            res = requests.post(WORKER_URL, headers=headers, timeout=60)
            print(f"📡 ワーカー応答コード: {res.status_code}")
            
            if res.status_code != 200:
                print(f"⚠️ ワーカー悲鳴 (エラー詳細): {res.text[:300]}")
            else:
                print("✅ 評価リクエスト正常受理！ (バックエンドでAIが評価中...)")
                
            time.sleep(5) # 連続で撃ち込みすぎないよう5秒待機
            
        if not found:
            print("⚠️ 該当する未評価データが見つかりませんでした。")
            
    except Exception as e:
        print(f"🚨 エラー発生: {e}")

if __name__ == "__main__":
    trigger_worker_manually()

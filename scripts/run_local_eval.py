import os
import sys
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# backendフォルダ内のモジュールを読み込めるようにパスを追加
sys.path.append(str(Path.cwd() / "backend"))
from services.ai_service import evaluate_and_update_task

def run_local_evaluation():
    load_dotenv() # 環境変数（APIキー等）の読み込み
    
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(key_path))
        firebase_admin.initialize_app(cred)
        
    db = firestore.client()
    
    print("🔍 未評価 (status: 0) の注入作品を捜索中...")
    docs = db.collection("nazokake_items").where("author", "==", "Takeshi_Gemini_Brainstorm").stream()
    
    found = False
    for doc in docs:
        data = doc.to_dict()
        if data.get("status") != 0:
            continue
            
        found = True
        doc_id = doc.id
        title = data.get("A_TITLE", "不明")
        text = data.get("nazokake_text", "")
        
        print(f"\n🚀 お題: {title} の評価エンジンをローカルで直接起動します！")
        # 魔法のAI関数を直接呼び出し
        evaluate_and_update_task(db, doc_id, title, text)
        print(f"✅ {title} の評価・保存が完了しました！")

    if not found:
        print("⚠️ 未評価のデータは見つかりませんでした。")

if __name__ == "__main__":
    run_local_evaluation()

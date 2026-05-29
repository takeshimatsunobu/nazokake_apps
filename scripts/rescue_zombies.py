import sys
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

sys.path.append(str(Path.cwd() / "backend"))
from services.ai_service import evaluate_and_update_task

def rescue_zombies():
    load_dotenv()
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 データベース全体から『鑑定中(未完了)』のゾンビデータを捜索します...")
    
    # 🚨 author等で絞らず、全データの中から「評価が完了していない(status != 2)」ものを探す
    docs = db.collection("nazokake_items").stream()
    
    count = 0
    for doc in docs:
        data = doc.to_dict()
        status = data.get("status", 0)
        
        # ステータス2(評価完了)ではないデータがターゲット
        if status != 2:
            title = data.get("A_TITLE", "不明")
            text = data.get("nazokake_text", "")
            doc_id = doc.id
            
            print(f"\n🧟 ゾンビデータ発見: お題「{title}」")
            print("🚀 AI評価エンジンを起動し、救出(評価)を開始します...")
            
            try:
                # 魔法のAI関数を呼び出し、スコアを叩き込んで成仏させる
                evaluate_and_update_task(db, doc_id, title, text)
                count += 1
                print(f"✅ 「{title}」の評価・保存が完了しました！")
            except Exception as e:
                print(f"🚨 救出失敗 「{title}」: {e}")

    if count == 0:
        print("\n✨ 素晴らしい！『鑑定中』で止まっているゾンビデータは1件もありませんでした。")
    else:
        print(f"\n🎉 計 {count} 件のゾンビデータの評価・救出が完了しました！")

if __name__ == "__main__":
    rescue_zombies()

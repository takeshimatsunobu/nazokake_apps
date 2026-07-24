import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path

def check_status():
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    
    # 安全な初期化（以前成功したロジック）
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 直近に作成された5件のなぞかけの状態（ステータス）を確認します...")
    try:
        # 作成日時の降順で最新5件を取得
        docs = db.collection("nazokake_items").order_by("created_at", direction=firestore.Query.DESCENDING).limit(5).stream()
        
        found = False
        for doc in docs:
            found = True
            data = doc.to_dict()
            title = data.get("A_TITLE", "不明")
            status = data.get("status", "不明")
            author = data.get("author", "不明")
            has_scores = "あり" if len(data.get("scores", {})) > 0 else "なし"
            print(f"📌 お題: {title:<10} | 著者: {author:<25} | Status: {status} | AI評価: {has_scores}")
            
        if not found:
            print("⚠️ データが見つかりませんでした。")
            
    except Exception as e:
        print(f"🚨 エラー発生: {e}")

if __name__ == "__main__":
    check_status()

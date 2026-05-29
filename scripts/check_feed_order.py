import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path

def check_feed_order():
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 画面に表示されるはずの『最新15件』の真の並び順をダンプします...")
    print("-" * 70)
    try:
        # フロントエンドと全く同じ条件（created_at降順）で取得
        docs = db.collection("nazokake_items").order_by("created_at", direction=firestore.Query.DESCENDING).limit(15).stream()
        
        for i, doc in enumerate(docs):
            data = doc.to_dict()
            title = data.get("A_TITLE", "不明")
            status = data.get("status", "不明")
            author = data.get("author", "不明")
            created_at = data.get("created_at")
            c_type = type(created_at).__name__
            
            # 日付文字列を綺麗に整形
            date_str = str(created_at)[:19] if created_at else "日付なし"
            
            print(f"{i+1:02d}. お題: {title:<12} | Status: {status:>2} | 日付型: {c_type:<23} | {date_str}")
            
    except Exception as e:
        print(f"🚨 エラー発生: {e}")

if __name__ == "__main__":
    check_feed_order()

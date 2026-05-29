import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path
from datetime import datetime

def fix_timestamp_format():
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 Takeshi_Gemini_Brainstorm のデータを捜索中...")
    try:
        docs = db.collection("nazokake_items").where("author", "==", "Takeshi_Gemini_Brainstorm").stream()
        
        count = 0
        for doc in docs:
            count += 1
            data = doc.to_dict()
            title = data.get("A_TITLE", "不明")
            
            # 現在時刻を既存データと同じ形式の文字列（例: 2026-05-25T...）に変換
            now_str = datetime.now().isoformat()
            
            # created_at のみを文字列でピンポイント上書き更新
            db.collection("nazokake_items").document(doc.id).update({
                "created_at": now_str
            })
            
            print(f"✅ お題「{title}」の作成日時を文字列型({now_str})に修正し、一番上へ引き上げました！")
            
        if count == 0:
            print("⚠️ 対象データが見つかりませんでした。")
        else:
            print("🎉 全件の修正が完了しました！ブラウザをリロードしてください。")
            
    except Exception as e:
        print(f"🚨 エラー発生: {e}")

if __name__ == "__main__":
    fix_timestamp_format()

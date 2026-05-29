import os
import sys
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
import traceback

def check_schema():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    try:
        if not firebase_admin._apps:
            if key_path.exists():
                cred = credentials.Certificate(str(key_path))
                firebase_admin.initialize_app(cred)
            else:
                firebase_admin.initialize_app()
                
        db = firestore.client()
        
        print("🔍 Firestoreから直近のなぞかけデータを1件取得し、正確なスキーマを解析します...")
        docs = db.collection("nazokake_items").limit(1).stream()
        
        found = False
        for doc in docs:
            found = True
            data = doc.to_dict()
            print(f"\n✅ 取得成功 (ドキュメントID: {doc.id})")
            print("-" * 50)
            for key, value in data.items():
                val_type = type(value).__name__
                val_preview = str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
                print(f"🔑 {key:<20} | 型: {val_type:<10} | 値: {val_preview}")
            print("-" * 50)
        
        if not found:
            print("⚠️ データが見つかりませんでした。")
            
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        line_num = traceback.extract_tb(exc_traceback)[-1].lineno
        print(f"🚨 エラー発生 (行: {line_num}): {e}")

if __name__ == '__main__':
    check_schema()

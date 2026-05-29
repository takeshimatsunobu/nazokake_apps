import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path
from collections import Counter
import json

def investigate_evaluations():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    print("🚀 user_evaluations の中身を調査中...")
    
    # statusの型混在エラーを避けるため、直接ドキュメントを抽出
    docs = db.collection("nazokake_items").limit(500).stream()
    
    found_evals = False
    
    for doc in docs:
        data = doc.to_dict()
        evals = data.get("user_evaluations")
        
        # user_evaluations が存在し、かつ空ではない場合
        if evals:
            print("\n🎉 【人間の評価データを発見！】")
            print(f"ドキュメントID: {doc.id}")
            print(f"お題: {data.get('A_TITLE', '不明')}")
            print("評価の中身:")
            # 見やすくフォーマットして出力
            print(json.dumps(evals, indent=2, ensure_ascii=False))
            found_evals = True
            break # 1つ見つかれば構造がわかるので一旦ストップ
            
    if not found_evals:
        print("\n🤔 500件調べましたが、user_evaluations に値が入っているものが見つかりませんでした。")

if __name__ == '__main__':
    investigate_evaluations()

import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path

def find_the_truth():
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 全データから対象を直接検索し、キー(スキーマ)と型を出力します...\n")
    
    # 比較したい対象の文字列
    targets = ["大根役者", "秋の空"]
    docs = db.collection("nazokake_items").stream()
    
    found_count = 0
    for doc in docs:
        data = doc.to_dict()
        # キー名が不明な場合を考慮し、値全体からターゲット文字列を検索
        values_str = str(data.values())
        
        for target in targets:
            if target in values_str:
                print(f"={'='*50}")
                print(f"🎯 発見: 【{target}】 (ID: {doc.id})")
                print(f"={'='*50}")
                
                # キーをアルファベット順にソートして出力
                for k in sorted(data.keys()):
                    v = data[k]
                    t = type(v).__name__
                    v_str = str(v)[:60] + "..." if len(str(v)) > 60 else str(v)
                    print(f"{k:<20}: {v_str} (型: {t})")
                
                targets.remove(target)
                found_count += 1
                break
                
    if found_count == 0:
        print("\n🚨 該当データが存在しません。")

if __name__ == "__main__":
    find_the_truth()

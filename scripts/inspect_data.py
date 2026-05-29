import json
import firebase_admin
from firebase_admin import credentials, firestore

def make_serializable(obj):
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    elif hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return obj

def inspect_broken_data():
    print("\n================ [ 徹底解剖: エラー発生データの構造確認 ] ================")
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()

    # 画像に表示されているお題をピンポイントで検索
    target_title = "屋台から漂う香ばしい匂いにお腹が鳴る食べ歩き"
    print(f"🔍 検索中: A_TITLE == '{target_title}'")

    docs = db.collection("nazokake_items").where("A_TITLE", "==", target_title).limit(1).stream()
    
    found = False
    for doc in docs:
        found = True
        print(f"\n📂 ドキュメントID: {doc.id}")
        data = doc.to_dict()
        safe_data = make_serializable(data)
        
        print("👇 【本番データベースに保存されている生のJSON構造】 👇\n")
        print(json.dumps(safe_data, ensure_ascii=False, indent=2))
        print("\n👆 ======================================================== 👆")
        
    if not found:
        print("⚠️ 該当するお題のデータが見つかりませんでした。")

if __name__ == "__main__":
    inspect_broken_data()

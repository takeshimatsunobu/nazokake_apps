import os
import json
import traceback
import firebase_admin
from firebase_admin import credentials, firestore

def make_serializable(obj):
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    elif hasattr(obj, 'isoformat'):
        return obj.isoformat()
    elif hasattr(obj, 'path'): 
        return obj.path
    else:
        return obj

def extract_all_raw_data_fixed():
    print("\n================ [ フェーズ3改修: Firestore ゾンビデータ全救出 ] ================")
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        
        db = firestore.client()
        
        print("⏳ Firestoreから 'status: 2' の【完全な全データ】を取得中...")
        
        # 🚨 【修正の核心】 order_by("timestamp") を削除！
        # これにより、timestampが存在しないゾンビデータも全て救出対象になります。
        docs = db.collection("nazokake_items").where("status", "==", 2).stream()
        
        extracted_data = []
        count = 0
        for doc in docs:
            safe_data = make_serializable(doc.to_dict())
            
            extracted_data.append({
                "id": doc.id,
                "data": safe_data
            })
            
            count += 1
            if count % 1000 == 0:
                print(f"  ... {count}件 救出完了")
        
        if not extracted_data:
            print("⚠️ 警告: 対象データが見つかりませんでした。")
            return

        os.makedirs("data", exist_ok=True)
        # 上書き保存します
        output_file = "data/raw_firestore_dump_all.json"
        
        print("💾 データをローカルファイルに保存しています...")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ 救出完了！ 合計 {len(extracted_data)}件のデータを {output_file} に保存しました。")

    except Exception as e:
        print(f"🚨 データ抽出中に致命的エラーが発生しました:")
        traceback.print_exc()

if __name__ == "__main__":
    extract_all_raw_data_fixed()

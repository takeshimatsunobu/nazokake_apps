import os
import json
import traceback
import firebase_admin
from firebase_admin import firestore

# ==========================================
# 🛡️ 型変換のヘルパー関数 (深い階層まで探索)
# ==========================================
def make_serializable(obj):
    """
    辞書やリストの奥深くまで潜り、Firestore特有の型（Datetime等）を
    JSONで保存できる文字列に変換する。
    """
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    elif hasattr(obj, 'isoformat'):
        # DatetimeWithNanoseconds などの日付型を文字列にする
        return obj.isoformat()
    # 必要であれば、Firestoreの参照型（DocumentReference）などもここで処理可能
    elif hasattr(obj, 'path'): 
        return obj.path
    else:
        return obj

def extract_all_raw_data():
    print("\n================ [ フェーズ3改: Firestore 全件 深層抽出 ] ================")
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        
        db = firestore.client()
        
        print("⏳ Firestoreから 'status: 2' の【全データ】を取得中... (通信に数分かかる場合があります)")
        
        docs = db.collection("nazokake_items").where("status", "==", 2).order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
        
        extracted_data = []
        count = 0
        for doc in docs:
            # 取得したデータを、深い階層まで全て安全な型に変換する
            safe_data = make_serializable(doc.to_dict())
            
            extracted_data.append({
                "id": doc.id,
                "data": safe_data
            })
            
            count += 1
            if count % 1000 == 0:
                print(f"  ... {count}件 取得完了")
        
        if not extracted_data:
            print("⚠️ 警告: 対象データが見つかりませんでした。")
            return

        os.makedirs("data", exist_ok=True)
        output_file = "data/raw_firestore_dump_all.json"
        
        print("💾 データをローカルファイルに保存しています...")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ 抽出完了！ 合計 {len(extracted_data)}件のデータを {output_file} に保存しました。")

    except Exception:
        print("🚨 データ抽出中に致命的エラーが発生しました:")
        traceback.print_exc()

if __name__ == "__main__":
    extract_all_raw_data()

import os
import json
import traceback
import firebase_admin
from firebase_admin import credentials, firestore

def extract_raw_data():
    print("\n================ [ フェーズ2-1: Firestore データ安全抽出 ] ================")
    try:
        # 1. 認証 (ADCへの安全なフォールバック)
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        
        db = firestore.client()
        
        # 2. データの取得 (テストとして最新50件を抽出)
        print("⏳ Firestoreから 'status: 2' のデータを取得中...")
        # ※暗黙の除外フィルターに注意: timestampが存在しないデータはスキップされます
        docs = db.collection("nazokake_items").where("status", "==", 2).order_by("timestamp", direction=firestore.Query.DESCENDING).limit(50).stream()
        
        extracted_data = []
        for doc in docs:
            data = doc.to_dict()
            
            # DatetimeWithNanoseconds型をJSONで保存できるように文字列に変換
            for key, value in data.items():
                if hasattr(value, 'isoformat'):
                    data[key] = value.isoformat()
            
            extracted_data.append({
                "id": doc.id,
                "data": data
            })
        
        if not extracted_data:
            print("⚠️ 警告: 対象データが見つかりませんでした。")
            return

        # 3. ローカルへの安全な保存
        os.makedirs("data", exist_ok=True)
        output_file = "data/raw_firestore_dump.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ 抽出完了！ {len(extracted_data)}件のデータを {output_file} に保存しました。")
        print("💡 [アーキテクトからの報告]: この操作は『読み取り専用』です。Firestore本体のデータは一切変更されていません。")

    except Exception as e:
        print(f"🚨 データ抽出中に致命的エラーが発生しました:")
        traceback.print_exc()

if __name__ == "__main__":
    extract_raw_data()

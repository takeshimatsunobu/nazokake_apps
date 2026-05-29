import json
import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import traceback

def inject_cleaned_data():
    print("\n================ [ フェーズ2-3: Firestore データ安全注入 (テスト3件) ] ================")
    
    # 1. 認証チェック
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()

    # 2. 浄化済みデータの読み込み
    clean_file_path = "data/clean_test_dump.json"
    if not os.path.exists(clean_file_path):
        print("🚨 エラー: 浄化済みデータが見つかりません。")
        return
        
    with open(clean_file_path, "r", encoding="utf-8") as f:
        cleaned_data = json.load(f)

    print(f"🚀 {len(cleaned_data)}件の浄化済みデータを、本番DBに反映します...")

    # 3. データの型復元とFirestoreへの書き込み
    success_count = 0
    for item in cleaned_data:
        doc_id = item["id"]
        data = item["data"]
        
        try:
            # 【絶対防衛線】文字列になっているtimestampを、本物の時刻型に復元する
            if "timestamp" in data and isinstance(data["timestamp"], str):
                # ISO 8601文字列をPythonのdatetimeオブジェクトに変換
                ts_str = data["timestamp"].replace("Z", "+00:00")
                data["timestamp"] = datetime.fromisoformat(ts_str)
                
            if "evaluated_at" in data and isinstance(data["evaluated_at"], str):
                ts_str = data["evaluated_at"].replace("Z", "+00:00")
                data["evaluated_at"] = datetime.fromisoformat(ts_str)
                
        except Exception as e:
            print(f"  ⚠️ ID: {doc_id} の日付型復元に失敗しました。スキップします: {e}")
            continue
            
        try:
            # Firestoreのドキュメントを「更新（update）」する（※余計なフィールドは消さず、対象だけ上書き）
            db.collection("nazokake_items").document(doc_id).update(data)
            print(f"  ✅ ID: {doc_id} (お題: {data.get('A_TITLE', '不明')}) の本番反映に成功！")
            success_count += 1
        except Exception as e:
            print(f"  🚨 ID: {doc_id} の反映中にエラーが発生しました: {e}")
            
    print(f"\n🎉 注入完了！ {success_count}/{len(cleaned_data)} 件のクリーンなデータを本番環境に反映しました。")
    print("💡 これで [抽出] -> [浄化] -> [注入] のフルパイプラインが完全開通しました！")

if __name__ == "__main__":
    try:
        inject_cleaned_data()
    except Exception as e:
        print(f"🚨 致命的なエラー: {e}")
        traceback.print_exc()

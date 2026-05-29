import json
import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

def recursive_restore_dates(obj):
    """
    辞書やリストの奥深くまで潜り、「日付のISO文字列」を発見したら
    すべてPythonのdatetime型（FirestoreがTimestampとして認識する型）に蘇生する。
    """
    if isinstance(obj, dict):
        return {k: recursive_restore_dates(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [recursive_restore_dates(v) for v in obj]
    elif isinstance(obj, str):
        # 2024-05-26T12:00... のようなISOフォーマット文字列か判定
        if len(obj) >= 19 and "T" in obj:
            try:
                # タイムゾーン情報を付与してdatetime型に変換
                ts_str = obj.replace("Z", "+00:00")
                return datetime.fromisoformat(ts_str)
            except ValueError:
                return obj # 日付文字列でなければそのまま返す
        return obj
    else:
        return obj

def inject_type_fix():
    print("\n================ [ 最終防衛線: 深層・型蘇生バッチの実行 ] ================")
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()

    clean_file_path = "data/clean_prod_dump_9500.jsonl"
    if not os.path.exists(clean_file_path):
        print("🚨 エラー: クリーンデータが見つかりません。")
        return

    print("⏳ ローカルのクリーンデータを読み込み、すべての時刻型を蘇生中...")
    cleaned_items = []
    with open(clean_file_path, "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line.strip())
            # 【重要】再帰的関数で、どこに潜む日付もすべて時刻型に戻す
            item["data"] = recursive_restore_dates(item["data"])
            cleaned_items.append(item)

    total_items = len(cleaned_items)
    print(f"🚀 Google Cloudへ修正データを高速一括送信します...")

    CHUNK_SIZE = 400
    success_count = 0

    for i in range(0, total_items, CHUNK_SIZE):
        chunk = cleaned_items[i:i + CHUNK_SIZE]
        batch = db.batch()
        
        for item in chunk:
            doc_id = item["id"]
            doc_ref = db.collection("nazokake_items").document(doc_id)
            # merge=True で上書き更新
            batch.set(doc_ref, item["data"], merge=True)
            
        try:
            batch.commit()
            success_count += len(chunk)
            print(f"  ... {success_count}/{total_items} 件 型蘇生完了")
        except Exception as e:
            print(f"  🚨 バッチ送信エラー: {e}")

    print(f"\n🎉 型蘇生コンプリート！すべての時刻データがFirestore本来の姿を取り戻しました。")

if __name__ == "__main__":
    inject_type_fix()

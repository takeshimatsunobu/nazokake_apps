import json
import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import traceback

def restore_types(data):
    """文字列になっている日付データを、Firestoreが愛する本物の時刻型に蘇生させる"""
    for key in ["timestamp", "evaluated_at", "created_at"]:
        if key in data and isinstance(data[key], str):
            try:
                # ISO 8601文字列をPythonのdatetimeオブジェクトに変換
                ts_str = data[key].replace("Z", "+00:00")
                data[key] = datetime.fromisoformat(ts_str)
            except Exception:
                pass
    return data

def inject_to_firestore():
    print("\n================ [ 最終フェーズ: 本番Firestore 高速一括注入 (Batched Writes) ] ================")
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()

    clean_file_path = "data/clean_prod_dump_9500.jsonl"
    if not os.path.exists(clean_file_path):
        print(f"🚨 エラー: クリーンデータ ({clean_file_path}) が見つかりません。")
        return

    print("⏳ ローカルのクリーンデータを読み込んでいます...")
    cleaned_items = []
    with open(clean_file_path, "r", encoding="utf-8") as f:
        for line in f:
            cleaned_items.append(json.loads(line.strip()))

    total_items = len(cleaned_items)
    print(f"📊 注入準備完了: {total_items}件のデータを本番に反映します。")
    print("🚀 Google Cloudへ高速一括送信を開始します (数十秒〜数分かかります)...")

    # Firestoreは最大500件ずつしか一括処理できないため、チャンク（塊）に分ける
    CHUNK_SIZE = 400
    success_count = 0

    for i in range(0, total_items, CHUNK_SIZE):
        chunk = cleaned_items[i:i + CHUNK_SIZE]
        batch = db.batch()
        
        for item in chunk:
            doc_id = item["id"]
            data = restore_types(item["data"])
            
            # ドキュメントの参照を取得し、バッチに「更新(merge=True)」の指示を追加
            doc_ref = db.collection("nazokake_items").document(doc_id)
            batch.set(doc_ref, data, merge=True)
            
        try:
            # チャンクをまとめて送信（コミット）
            batch.commit()
            success_count += len(chunk)
            print(f"  ... {success_count}/{total_items} 件 反映完了")
        except Exception as e:
            print(f"  🚨 バッチ送信エラー (チャンク {i}〜): {e}")

    print(f"\n🎉 注入ミッション・コンプリート！")
    print(f"🏆 合計 {success_count}件 のピカピカのデータが、本番データベースに完全上書きされました。")

if __name__ == "__main__":
    try:
        inject_to_firestore()
    except Exception as e:
        print(f"🚨 致命的なエラー: {e}")
        traceback.print_exc()

import json
import os
import firebase_admin
from firebase_admin import credentials, firestore

def inject_total_score():
    print("\n================ [ 最終パッチ: 総合点(total_score)の算出と注入 ] ================")
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()

    clean_file_path = "data/clean_prod_dump_9500.jsonl"
    if not os.path.exists(clean_file_path):
        print("🚨 エラー: クリーンデータが見つかりません。")
        return

    cleaned_items = []
    with open(clean_file_path, "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line.strip())
            data = item.get("data", {})
            scores = data.get("scores", {})
            
            if scores and isinstance(scores, dict):
                # 11項目の平均値を計算し、5点満点にスケール変換 (小数第2位まで)
                avg_score = sum(scores.values()) / len(scores)
                total_score = round(avg_score * 5, 2)
                cleaned_items.append({"id": item["id"], "total_score": total_score})

    print(f"📊 {len(cleaned_items)}件の総合点を算出しました。本番DBへ反映します...")
    
    CHUNK_SIZE = 400
    success_count = 0
    for i in range(0, len(cleaned_items), CHUNK_SIZE):
        chunk = cleaned_items[i:i + CHUNK_SIZE]
        batch = db.batch()
        for item in chunk:
            doc_ref = db.collection("nazokake_items").document(item["id"])
            # フィールドのみをピンポイントで追加・更新
            batch.update(doc_ref, {"total_score": item["total_score"]})
        
        try:
            batch.commit()
            success_count += len(chunk)
            print(f"  ... {success_count}/{len(cleaned_items)} 件 注入完了")
        except Exception as e:
            print(f"  🚨 バッチ送信エラー: {e}")
            
    print("\n🎉 総合点の注入が完了しました！")

if __name__ == "__main__":
    inject_total_score()

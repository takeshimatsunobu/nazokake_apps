import os
import json
import time
from pathlib import Path
from google import genai
from google.genai import types
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# 💡 修正1: Vectorクラスを正しい場所から直接インポート
from google.cloud.firestore_v1.vector import Vector

def seed_rag_database():
    load_dotenv()

    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("🚨 エラー: GEMINI_API_KEY が設定されていません。")
        return
        
    client = genai.Client(api_key=api_key)

    data_path = current_dir / "data" / "sft_dataset.jsonl"
    if not data_path.exists():
        print(f"🚨 エラー: {data_path} が見つかりません。")
        return

    items_to_insert = []
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            items_to_insert.append(json.loads(line))
            
    print(f"🚀 {len(items_to_insert)}件のデータをベクトル化し、Firestoreに登録します...")
    print("⏳ API制限(429)を回避するため、ゆっくりと処理を進めます。お茶でも飲んでお待ちください...")
    
    collection_ref = db.collection("nazokake_rag_knowledge")
    
    batch = db.batch()
    batch_count = 0
    total_inserted = 0

    for item in items_to_insert:
        prompt_text = item["messages"][0]["content"]
        start_idx = prompt_text.find("お題「") + 3
        end_idx = prompt_text.find("」で、", start_idx)
        odai = prompt_text[start_idx:end_idx] if start_idx > 2 and end_idx > -1 else prompt_text
        
        answer_text = item["messages"][1]["content"]

        # 💡 修正2: 429エラー対策（自動リトライ機能）
        success = False
        max_retries = 5
        
        for attempt in range(max_retries):
            try:
                response = client.models.embed_content(
                    model='gemini-embedding-2',
                    contents=odai,
                )
                embedding = response.embeddings[0].values
                success = True
                break # 成功したらリトライループを抜ける
                
            except Exception as e:
                error_msg = str(e)
                if '429' in error_msg or 'RESOURCE_EXHAUSTED' in error_msg:
                    # 待機時間を徐々に延ばす（5秒, 10秒, 15秒...）
                    wait_time = 5 * (attempt + 1)
                    print(f"  ⏳ 制限到達。{wait_time}秒待機して再挑戦します... (お題: {odai})")
                    time.sleep(wait_time)
                else:
                    print(f"⚠️ 予期せぬエラー (お題: {odai}): {error_msg}")
                    break # 429以外の致命的なエラーは諦める

        if not success:
            print(f"❌ リトライ上限に達したためスキップしました: {odai}")
            continue

        try:
            doc_ref = collection_ref.document()
            batch.set(doc_ref, {
                "odai": odai,
                "nazokake": answer_text,
                # 💡 修正1: 正しいVectorで包む
                "embedding": Vector(embedding)
            })
            
            batch_count += 1
            total_inserted += 1
            
            # バッチサイズを200に下げて安全にコミット
            if batch_count >= 200:
                batch.commit()
                print(f"  ... {total_inserted} 件登録完了")
                batch = db.batch()
                batch_count = 0
                
        except Exception as e:
             print(f"⚠️ 保存エラー (お題: {odai}): {e}")

        # 💡 修正2: 平常時もAPIをパンクさせないよう、0.5秒ずつ休みながら進む
        time.sleep(0.5)

    if batch_count > 0:
        batch.commit()
        print(f"  ... {total_inserted} 件登録完了")

    print(f"✅ RAGデータベースの構築が完了しました！ (合計: {total_inserted}件)")

if __name__ == "__main__":
    seed_rag_database()

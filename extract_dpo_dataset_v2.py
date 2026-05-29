import json
import os
import random
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore

def extract_dpo_dataset_v2():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    print("🚀 Firestoreから status:2 のデータを取得中...")
    
    docs = db.collection("nazokake_items").where("status", "==", 2).stream()
    
    good_items = []
    bad_items = []
    
    for doc in docs:
        data = doc.to_dict()
        score = data.get("user_score", 0)
        
        # 評価が高いものをChosen候補、低いものをRejected候補に分ける
        if score >= 4:
            good_items.append({
                "odai": data.get("A_TITLE", ""),
                "text": data.get("nazokake_text", "")
            })
        elif score <= 2:
            bad_items.append({
                "odai": data.get("A_TITLE", ""),  # 使わないが念のため保持
                "text": data.get("nazokake_text", "")
            })
            
    print(f"📊 高評価データ(Chosen候補): {len(good_items)}件")
    print(f"📊 低評価データ(Rejected候補): {len(bad_items)}件")
    
    dpo_dataset = []
    
    # 少ない方のリストの長さに合わせてペアを作成
    pair_count = min(len(good_items), len(bad_items))
    
    if pair_count > 0:
        # ランダム性を担保するためにシャッフル
        random.shuffle(good_items)
        random.shuffle(bad_items)
        
        for i in range(pair_count):
            chosen = good_items[i]
            rejected = bad_items[i]
            
            dpo_dataset.append({
                "prompt": f"お題「{chosen['odai']}」で、誰もが納得する大衆性を持った秀逸ななぞかけを作成してください。",
                "chosen": chosen['text'],
                "rejected": rejected['text']  # 異なるお題に対する悪い回答だが、避けたい「傾向」として学習させる
            })
            
    output_dir = current_dir / "data"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "dpo_dataset.jsonl"
    
    with open(output_path, "w", encoding="utf-8") as f:
        for item in dpo_dataset:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"✅ DPO用データ抽出完了: {len(dpo_dataset)}件のペアを {output_path} に保存しました。")

if __name__ == "__main__":
    extract_dpo_dataset_v2()

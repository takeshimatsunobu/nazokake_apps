import json
import os
import random
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

def extract_dpo_dataset_v6():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    print("🚀 救出開始！ status:2 のデータから user_evaluations を抽出中...")
    
    # 警告を避けて安全にクエリ
    docs = db.collection("nazokake_items").where(filter=FieldFilter("status", "==", 2)).stream()
    
    good_items = []
    bad_items = []
    
    for doc in docs:
        data = doc.to_dict()
        evals = data.get("user_evaluations", [])
        
        # 評価配列が存在しない、または空の場合はスキップ
        if not evals or not isinstance(evals, list):
            continue
            
        # 配列の中から最新の評価（配列の最後尾）または最大の評価を取得する
        # ここではシンプルに、配列内にある最初の評価スコアを採用する
        score = evals[0].get("user_score", 0)
        
        # 抽出条件
        if score >= 3:
            good_items.append({
                "odai": data.get("A_TITLE", ""),
                "text": data.get("nazokake_text", "")
            })
        elif score <= 2 and score > 0: # 0（未評価）は弾く
            bad_items.append({
                "odai": data.get("A_TITLE", ""),
                "text": data.get("nazokake_text", "")
            })
            
    print(f"📊 Chosen候補 (スコア3以上): {len(good_items)}件")
    print(f"📊 Rejected候補 (スコア1, 2): {len(bad_items)}件")
    
    dpo_dataset = []
    pair_count = min(len(good_items), len(bad_items))
    
    if pair_count > 0:
        random.shuffle(good_items)
        random.shuffle(bad_items)
        for i in range(pair_count):
            dpo_dataset.append({
                "prompt": f"お題「{good_items[i]['odai']}」で、誰もが納得する大衆性を持った秀逸ななぞかけを作成してください。",
                "chosen": good_items[i]['text'],
                "rejected": bad_items[i]['text']
            })
            
    output_dir = current_dir / "data"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "dpo_dataset.jsonl"
    
    with open(output_path, "w", encoding="utf-8") as f:
        for item in dpo_dataset:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"✅ DPO用データ抽出完了: {len(dpo_dataset)}件のペアを {output_path} に保存しました。")

if __name__ == "__main__":
    extract_dpo_dataset_v6()

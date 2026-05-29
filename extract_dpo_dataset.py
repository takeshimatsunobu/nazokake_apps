import json
import os
from pathlib import Path
from collections import defaultdict
import firebase_admin
from firebase_admin import credentials, firestore

def extract_dpo_dataset():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            # 鍵ファイルがない場合はデフォルト認証にフォールバック（Takeshiオリジナル仕様）
            firebase_admin.initialize_app()
            
    db = firestore.client()
    print("🚀 Firestoreから status:2 のデータを取得し、DPOペアを構築中...")
    
    docs = db.collection("nazokake_items").where("status", "==", 2).stream()
    
    grouped_data = defaultdict(list)
    for doc in docs:
        data = doc.to_dict()
        odai = data.get("A_TITLE")
        if not odai:
            continue
        grouped_data[odai].append({
            "text": data.get("nazokake_text", ""),
            "score": data.get("user_score", 0)
        })
    
    dpo_dataset = []
    for odai, items in grouped_data.items():
        if len(items) < 2:
            continue
        # スコア順にソート
        items.sort(key=lambda x: x["score"], reverse=True)
        best = items[0]
        worst = items[-1]
        
        # 評価に差がある場合のみペアとして採用
        if best["score"] > worst["score"]:
            dpo_dataset.append({
                "prompt": f"お題「{odai}」で、誰もが納得する大衆性を持った秀逸ななぞかけを作成してください。",
                "chosen": best["text"],
                "rejected": worst["text"]
            })

    output_dir = current_dir / "data"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "dpo_dataset.jsonl"
    
    with open(output_path, "w", encoding="utf-8") as f:
        for item in dpo_dataset:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"✅ DPO用データ抽出完了: {len(dpo_dataset)}件のペアを {output_path} に保存しました。")

if __name__ == "__main__":
    extract_dpo_dataset()

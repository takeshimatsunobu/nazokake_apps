import json
import os
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

def extract_sft_dataset():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    print("🚀 SFT用教師データの抽出を開始します...")
    
    docs = db.collection("nazokake_items").where(filter=FieldFilter("status", "==", 2)).stream()
    
    sft_dataset = []
    
    for doc in docs:
        data = doc.to_dict()
        evals = data.get("user_evaluations", [])
        
        if not evals or not isinstance(evals, list):
            continue
            
        # 配列の先頭のスコアを取得
        score = evals[0].get("user_score", 0)
        
        # 評価が3以上のものを「正解データ（教師データ）」として採用
        if score >= 3:
            odai = data.get("A_TITLE", "")
            nazokake = data.get("nazokake_text", "")
            
            if not odai or not nazokake:
                continue
                
            # 一般的なSFTフォーマット（Hugging Face等の標準的な messages 形式）
            sft_dataset.append({
                "messages": [
                    {"role": "user", "content": f"お題「{odai}」で、誰もが納得する大衆性を持った秀逸ななぞかけを作成してください。"},
                    {"role": "assistant", "content": nazokake}
                ]
            })
            
    output_dir = current_dir / "data"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "sft_dataset.jsonl"
    
    with open(output_path, "w", encoding="utf-8") as f:
        for item in sft_dataset:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"✅ SFT用データ抽出完了: {len(sft_dataset)}件の教師データを {output_path} に保存しました。")

if __name__ == "__main__":
    extract_sft_dataset()

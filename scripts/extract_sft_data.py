import json
import os
from google.cloud import firestore

db = firestore.Client()

def extract_sft_data():
    print("🧠 [Phase 2] AI育成(SFT)用データの抽出を開始します...")
    
    # 評価完了(status=2)のデータを取得
    docs = db.collection("nazokake_items").where("status", "==", 2).stream()
    
    sft_data = []
    for doc in docs:
        data = doc.to_dict()
        odai = data.get("A_TITLE", "")
        nazo = data.get("nazokake_text", "")
        
        # お題とテキストが両方存在する場合のみ抽出
        if odai and nazo:
            sft_data.append({
                "messages": [
                    {"role": "user", "content": f"お題「{odai}」でなぞかけを作ってください。"},
                    {"role": "model", "content": nazo}
                ]
            })
            
    # dataフォルダが無ければ作成
    os.makedirs("data", exist_ok=True)
    
    # JSONL形式（1行1JSON）で書き出し
    output_path = "data/sft_dataset.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        for item in sft_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"✅ 抽出完了！ 合計 {len(sft_data)} 件の学習用データを '{output_path}' に生成しました。")

if __name__ == "__main__":
    extract_sft_data()

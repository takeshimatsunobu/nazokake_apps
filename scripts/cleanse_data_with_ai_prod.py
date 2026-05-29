import json
import os
import requests
import traceback
from pydantic import BaseModel, Field, ValidationError, ConfigDict

class NazokakeItemSchema(BaseModel):
    model_config = ConfigDict(extra='allow')
    A_TITLE: str = Field(..., description="お題のテキスト")
    nazokake_text: str = Field(..., description="なぞかけの本文")
    status: int = Field(..., description="ステータス")
    timestamp: str = Field(..., description="ISO 8601形式の日付文字列")

def cleanse_with_gemma(raw_item):
    url = "http://localhost:11434/api/generate"
    prompt = f"""
    あなたはデータクレンジングAIです。以下の生のJSONデータから、会話文やマークダウンを除外し、純粋なJSONオブジェクトのみを出力してください。
    【絶対遵守】: 'A_TITLE', 'nazokake_text', 'status', 'timestamp' のキーは絶対に削除せず、そのまま出力に含めてください。
    
    【生データ】
    {json.dumps(raw_item, ensure_ascii=False)}
    """
    
    payload = {
        "model": "gemma4:e4b",
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }
    response = requests.post(url, json=payload, timeout=30.0)
    response.raise_for_status()
    return json.loads(response.json().get("response", ""))

def main():
    print("\n================ [ 本番稼働: Gemma 4 全件データ浄化 ] ================")
    raw_file_path = "data/raw_firestore_dump.json"
    
    with open(raw_file_path, "r", encoding="utf-8") as f:
        all_raw_data = json.load(f)

    # リミッター解除！全50件を対象にセット
    print(f"🔥 リミッター解除: 全{len(all_raw_data)}件の連続クレンジングを開始します（少々時間がかかります）...")

    cleaned_results = []
    
    for i, item in enumerate(all_raw_data, 1):
        doc_id = item.get("id")
        raw_data = item.get("data", {})
        
        print(f"  [{i}/{len(all_raw_data)}] ID: {doc_id} を処理中...")
        try:
            ai_cleaned_dict = cleanse_with_gemma(raw_data)
            
            for essential_key in ["A_TITLE", "nazokake_text", "status", "timestamp"]:
                if essential_key not in ai_cleaned_dict and essential_key in raw_data:
                    ai_cleaned_dict[essential_key] = raw_data[essential_key]
                    
            validated_data = NazokakeItemSchema(**ai_cleaned_dict)
            cleaned_results.append({"id": doc_id, "data": validated_data.model_dump()})
            print(f"      ✅ 成功 (お題: {validated_data.A_TITLE})")
            
        except Exception as e:
            print(f"      🚨 エラー発生のためスキップ: {e}")

    if cleaned_results:
        # 本番用のファイル名で保存
        out_path = "data/clean_prod_dump.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_results, f, ensure_ascii=False, indent=2)
        print(f"\n🎉 クレンジング完了！ {len(cleaned_results)}件 のピカピカのデータを {out_path} に保存しました。")

if __name__ == "__main__":
    main()

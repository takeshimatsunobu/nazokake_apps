import json
import os
import requests
import traceback
from pydantic import BaseModel, Field, ValidationError, ConfigDict

# ==========================================
# 🛡️ Pydantic: 鉄壁の門番 (真のスキーマに最適化)
# ==========================================
class NazokakeItemSchema(BaseModel):
    model_config = ConfigDict(extra='allow')
    # ファクトに基づき、odai ではなく A_TITLE を必須キーとして定義
    A_TITLE: str = Field(..., description="お題のテキスト")
    nazokake_text: str = Field(..., description="なぞかけの本文")
    status: int = Field(..., description="ステータス")
    timestamp: str = Field(..., description="ISO 8601形式の日付文字列")

# ==========================================
# 🤖 Gemma 4: クレンジング関数（プロンプト最適化版）
# ==========================================
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
    
    # フェイルファスト
    response = requests.post(url, json=payload, timeout=30.0)
    response.raise_for_status()
    
    result_text = response.json().get("response", "")
    return json.loads(result_text)

# ==========================================
# 🚀 メインパイプライン (ハイブリッド復元搭載)
# ==========================================
def main():
    print("\n================ [ フェーズ2-2完全版: Gemma 4 × Pydantic (A_TITLE対応) ] ================")
    raw_file_path = "data/raw_firestore_dump.json"
    
    if not os.path.exists(raw_file_path):
        print("🚨 エラー: 抽出された生データが見つかりません。")
        return

    with open(raw_file_path, "r", encoding="utf-8") as f:
        all_raw_data = json.load(f)

    test_target = all_raw_data[:3]
    print(f"🔍 全{len(all_raw_data)}件中、最初の3件のテストを実行します...")

    cleaned_results = []
    
    for i, item in enumerate(test_target, 1):
        doc_id = item.get("id")
        raw_data = item.get("data", {})
        
        print(f"  [{i}/3] ドキュメントID: {doc_id} を処理中...")
        try:
            # 1. AIによる整形
            ai_cleaned_dict = cleanse_with_gemma(raw_data)
            
            # 2. Pythonによるハイブリッド復元 (A_TITLE対応)
            for essential_key in ["A_TITLE", "nazokake_text", "status", "timestamp"]:
                if essential_key not in ai_cleaned_dict and essential_key in raw_data:
                    ai_cleaned_dict[essential_key] = raw_data[essential_key]
                    print(f"      🩹 [復元発動]: AIが削った '{essential_key}' を元データから強制復元しました。")
            
            # 3. Pydantic門番による最終チェック
            validated_data = NazokakeItemSchema(**ai_cleaned_dict)
            final_dict = validated_data.model_dump()
            
            cleaned_results.append({
                "id": doc_id,
                "data": final_dict
            })
            print(f"      ✅ 浄化・検証成功！ (お題: {final_dict.get('A_TITLE')})")
            
        except ValidationError as ve:
            print(f"      🚨 【Pydantic門番発動】それでも型が不正です:\n{ve}")
        except Exception as e:
            print(f"      🚨 予期せぬエラー: {e}")

    # 結果を保存
    if cleaned_results:
        os.makedirs("data", exist_ok=True)
        out_path = "data/clean_test_dump.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_results, f, ensure_ascii=False, indent=2)
        print(f"\n🎉 突破成功！検証に合格した {len(cleaned_results)}件 を {out_path} に保存しました。")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"🚨 システムエラー: {e}")
        traceback.print_exc()

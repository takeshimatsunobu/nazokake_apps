import json
import os
import requests
import traceback
import time
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict

# ==========================================
# ⚙️ 設定と状態管理 (チェックポイント)
# ==========================================
RAW_FILE = "data/raw_firestore_dump_all.json"
CLEAN_FILE = "data/clean_prod_dump_9500.json"
CHECKPOINT_FILE = "data/batch_checkpoint.json"

class NazokakeItemSchema(BaseModel):
    model_config = ConfigDict(extra='allow')
    A_TITLE: str = Field(..., description="お題のテキスト")
    nazokake_text: str = Field(..., description="なぞかけの本文")
    status: int = Field(..., description="ステータス")
    timestamp: str = Field(..., description="ISO 8601形式の日付文字列")

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed_ids": [], "failed_ids": {}}

def save_checkpoint(state):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def cleanse_with_gemma_with_retry(raw_item, max_retries=3):
    url = "http://localhost:11434/api/generate"
    prompt = f"""
    あなたはデータクレンジングAIです。以下の生のJSONデータから、会話文やマークダウンを除外し、純粋なJSONオブジェクトのみを出力してください。
    【絶対遵守】: 'A_TITLE', 'nazokake_text', 'status', 'timestamp' のキーは絶対に削除せず、そのまま出力に含めてください。
    
    【生データ】
    {json.dumps(raw_item, ensure_ascii=False)}
    """
    
    payload = {"model": "gemma4:e4b", "prompt": prompt, "stream": False, "format": "json"}
    
    for attempt in range(1, max_retries + 1):
        try:
            current_timeout = 30.0 + (attempt * 30.0)
            if attempt > 1:
                print(f"        🔄 [リトライ {attempt}/{max_retries}] AI待機中 ({current_timeout}秒)...")
                time.sleep(2)
                
            response = requests.post(url, json=payload, timeout=current_timeout)
            response.raise_for_status()
            return json.loads(response.json().get("response", ""))
            
        except requests.exceptions.Timeout:
            if attempt == max_retries:
                raise Exception(f"タイムアウト({max_retries}回)")
        except Exception as e:
            if attempt == max_retries:
                raise Exception(f"エラー: {e}")

# ==========================================
# 🚀 メインパイプライン (ゾンビ対応・レジューム稼働)
# ==========================================
def main():
    print("\n================ [ エンタープライズ稼働: 9,440件 レジューム浄化バッチ ] ================")
    
    if not os.path.exists(RAW_FILE):
        print(f"🚨 エラー: 生データが見つかりません。")
        return

    with open(RAW_FILE, "r", encoding="utf-8") as f:
        all_raw_data = json.load(f)

    state = load_checkpoint()
    processed_count = len(state["processed_ids"])
    
    print(f"📊 総データ数: {len(all_raw_data)}件 | 完了済: {processed_count}件 | エラー: {len(state['failed_ids'])}件")
    print(f"🔥 未処理の {len(all_raw_data) - processed_count}件 のクレンジングを開始します (Ctrl+Cで安全に中断可能)...")

    cleaned_results = []
    if os.path.exists(CLEAN_FILE):
        with open(CLEAN_FILE, "r", encoding="utf-8") as f:
            cleaned_results = json.load(f)

    for i, item in enumerate(all_raw_data, 1):
        doc_id = item.get("id")
        
        # 🟢 処理済みの場合はスキップ（レジューム機能）
        if doc_id in state["processed_ids"]:
            continue
            
        raw_data = item.get("data", {})
        print(f"\n  [{i}/{len(all_raw_data)}] ID: {doc_id} を処理中...")
        
        try:
            ai_cleaned_dict = cleanse_with_gemma_with_retry(raw_data)
            
            # 💉 【NEW】 ゾンビ蘇生ハイブリッド復元
            for essential_key in ["A_TITLE", "nazokake_text", "status", "timestamp"]:
                if essential_key not in ai_cleaned_dict:
                    if essential_key in raw_data:
                        ai_cleaned_dict[essential_key] = raw_data[essential_key]
                    elif essential_key == "timestamp":
                        # 時間がないゾンビデータには、現在時刻(UTC)を自動注入して蘇生
                        ai_cleaned_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
                        print("      🩹 [ゾンビ蘇生]: 欠損していたtimestampを自動補完しました。")
                    
            validated_data = NazokakeItemSchema(**ai_cleaned_dict)
            
            cleaned_results.append({"id": doc_id, "data": validated_data.model_dump()})
            state["processed_ids"].append(doc_id)
            
            with open(CLEAN_FILE, "w", encoding="utf-8") as f:
                json.dump(cleaned_results, f, ensure_ascii=False, indent=2)
            save_checkpoint(state)
            
            print(f"      ✅ 成功＆保存完了 (お題: {validated_data.A_TITLE})")
            
        except Exception as e:
            print(f"      🚨 失敗: {e} -> スキップして記録します。")
            state["failed_ids"][doc_id] = str(e)
            save_checkpoint(state)

    print("\n🎉 全件の処理ループが完了しました！")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 ユーザーによって安全に中断されました。次回は続きから再開できます。")

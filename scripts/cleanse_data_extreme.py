import json
import os
import requests
import traceback
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pydantic import BaseModel, Field, ConfigDict

# ==========================================
# ⚙️ 設定 (I/O爆発を防ぐJSONL形式に変更)
# ==========================================
RAW_FILE = "data/raw_firestore_dump_all.json"
CLEAN_FILE_JSONL = "data/clean_prod_dump_9500.jsonl"
CHECKPOINT_FILE = "data/batch_checkpoint_v2.json"

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

# ==========================================
# 🛡️ 改革1: Pydantic先行チェック (AIバイパス)
# ==========================================
def fast_track_validation(raw_data):
    """
    AIに投げる前に、Python側だけで高速チェック。
    ここで合格すればAIの推論時間（数十秒）が【0秒】になります。
    """
    try:
        # 必要なキーが揃っているか最低限のチェック
        essential_keys = ["A_TITLE", "nazokake_text", "status"]
        if all(k in raw_data for k in essential_keys):
            # timestampがない場合は自己修復
            if "timestamp" not in raw_data:
                raw_data["timestamp"] = datetime.now(timezone.utc).isoformat()
            
            # 型チェック（余計なキーはPydanticが自動で許容・整理する）
            validated = NazokakeItemSchema(**raw_data)
            return validated.model_dump()
    except Exception:
        pass
    return None # 合格しなかった場合はNoneを返し、AIに託す

# ==========================================
# 🤖 改革2: LLMクレンジング (最後の砦)
# ==========================================
def cleanse_with_gemma(raw_item, doc_id, max_retries=2):
    url = "http://localhost:11434/api/generate"
    prompt = f"""
    あなたはデータクレンジングAIです。以下の生のJSONデータから純粋なJSONオブジェクトのみを出力してください。
    【絶対遵守】: 'A_TITLE', 'nazokake_text', 'status', 'timestamp' は必ず含める。
    {json.dumps(raw_item, ensure_ascii=False)}
    """
    payload = {"model": "gemma4:e4b", "prompt": prompt, "stream": False, "format": "json"}
    
    for attempt in range(1, max_retries + 1):
        try:
            timeout = 40.0
            response = requests.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            ai_cleaned = json.loads(response.json().get("response", ""))
            
            # ハイブリッド復元
            for k in ["A_TITLE", "nazokake_text", "status", "timestamp"]:
                if k not in ai_cleaned and k in raw_item:
                    ai_cleaned[k] = raw_item[k]
            if "timestamp" not in ai_cleaned:
                ai_cleaned["timestamp"] = datetime.now(timezone.utc).isoformat()
                
            return NazokakeItemSchema(**ai_cleaned).model_dump()
        except Exception as e:
            if attempt == max_retries:
                raise Exception(f"AI処理失敗: {e}")

# ==========================================
# 🚀 改革3: 並列ワーカー関数
# ==========================================
def process_single_document(item):
    doc_id = item.get("id")
    raw_data = item.get("data", {})
    
    # 1. まずは超高速のPythonチェック (バイパス)
    clean_data = fast_track_validation(raw_data)
    used_ai = False
    
    if clean_data:
        status_msg = "⚡ 高速パス(AIスキップ)"
    else:
        # 2. ダメだった時だけAIを召喚する
        clean_data = cleanse_with_gemma(raw_data, doc_id)
        status_msg = "🤖 AI浄化完了"
        used_ai = True
        
    return {"id": doc_id, "data": clean_data}, status_msg, used_ai

def main():
    print("\n================ [ 極・エンタープライズ稼働: 高速並列バッチ ] ================")
    
    if not os.path.exists(RAW_FILE):
        return print("🚨 生データが見つかりません。")

    with open(RAW_FILE, "r", encoding="utf-8") as f:
        all_raw_data = json.load(f)

    state = load_checkpoint()
    
    # 未処理のデータだけを抽出
    pending_items = [item for item in all_raw_data if item["id"] not in state["processed_ids"]]
    
    print(f"📊 総データ: {len(all_raw_data)}件 | 残り未処理: {len(pending_items)}件")
    print("🚀 マルチスレッド(3並列) ＆ AIバイパス機能 で処理を開始します...")

    # 改革3: ThreadPoolExecutor で 3件ずつ並列処理
    MAX_WORKERS = 3
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # タスクをキューに投入
        future_to_doc = {executor.submit(process_single_document, item): item for item in pending_items}
        
        count = 0
        for future in as_completed(future_to_doc):
            item = future_to_doc[future]
            doc_id = item["id"]
            count += 1
            
            try:
                result_data, status_msg, used_ai = future.result()
                
                # 改革1: JSONL形式でファイルの「末尾に追記 (mode='a')」 (一瞬で終わる)
                with open(CLEAN_FILE_JSONL, "a", encoding="utf-8") as f:
                    # 1行の文字列としてJSONを書き込む
                    f.write(json.dumps(result_data, ensure_ascii=False) + "\n")
                
                # 状態を更新
                state["processed_ids"].append(doc_id)
                save_checkpoint(state)
                print(f"  [{count}/{len(pending_items)}] ID:{doc_id} -> {status_msg}")
                
            except Exception as e:
                print(f"  [{count}/{len(pending_items)}] ID:{doc_id} -> 🚨 エラー: {e}")
                state["failed_ids"][doc_id] = str(e)
                save_checkpoint(state)

    print("\n🎉 極・高速バッチ処理が完了しました！")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 安全に中断されました。")

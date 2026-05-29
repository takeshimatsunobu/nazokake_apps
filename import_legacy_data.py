import os
import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

CURRENT_DIR = Path(__file__).resolve().parent
ARCHIVE_PATH = CURRENT_DIR / "data" / "evaluation_archive.jsonl"
CSV_PATH = CURRENT_DIR / "data" / "output_results.csv"

# --- 初期化 ---
try:
    key_path = CURRENT_DIR / "backend" / "serviceAccountKey.json"
    if key_path.exists():
        cred = credentials.Certificate(str(key_path))
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.initialize_app()
    db = firestore.client()
except Exception as e:
    print(f"❌ Firestore初期化エラー: {e}")
    exit(1)

API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

# --- 判定ロジック ---

def is_duplicate(odai, text):
    """【重複チェック】Firestoreを検索し、完全に一致するデータがないか確認する"""
    docs = db.collection("nazokake_items").where("A_TITLE", "==", odai).where("nazokake_text", "==", text).limit(1).stream()
    return any(True for _ in docs) # 1件でも見つかれば True (重複)

def re_evaluate_with_ai(odai, text):
    print(f"⚖️ AI審査員による再採点中...")
    prompt = f"""あなたは厳格ななぞかけ審査員です。以下の作品を、現在の11の評価軸に基づいて精密に再評価してください。
    お題: {odai}
    なぞかけ: {text}
    【必ず以下のJSONのみ出力】
    {{"scores": {{"S_sur": 0.2, "S_emo": 0.9, "S_tech": 0.3}}, "reasoning": "詳細な講評"}}"""
    response = client.models.generate_content(
        model='gemini-3-flash-preview',
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.3)
    )
    return json.loads(re.search(r'\{.*\}', response.text.strip(), re.DOTALL).group(0))

def simulate_human_eval(odai, text):
    print(f"👤 仮想ユーザーによる感性評価中...")
    prompt = f"""一般視聴者として、このなぞかけに星1〜5をつけてください。
    お題: {odai}
    なぞかけ: {text}
    【必ず以下のJSONのみ出力】
    {{"star_score": 3, "comment": "感想"}}"""
    response = client.models.generate_content(
        model='gemini-3-flash-preview',
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.7)
    )
    return json.loads(re.search(r'\{.*\}', response.text.strip(), re.DOTALL).group(0))

def process_import(odai, text):
    """1件のデータを処理する"""
    print(f"\n--- 処理開始: お題「{odai}」 ---")
    
    # 🛡️ 重複チェック（はじく処理）
    if is_duplicate(odai, text):
        print(f"⏭️ スキップ: 既にデータベースに存在する作品です。")
        return False
        
    try:
        ai_result = re_evaluate_with_ai(odai, text)
        human_result = simulate_human_eval(odai, text)
        
        score = human_result.get("star_score", 3)
        deviation = score - 3
        
        doc_ref = db.collection("nazokake_items").document()
        now_str = datetime.now().isoformat()
        
        item_data = {
            "A_TITLE": odai,
            "nazokake_text": text,
            "scores": ai_result.get("scores", {}),
            "reasoning": ai_result.get("reasoning", ""),
            "status": "completed",
            "created_at": now_str,
            "is_golden": False,
            "author": "Legacy_Import",
            "user_evaluations": [{
                "timestamp": now_str,
                "user_score": score,
                "deviation": deviation,
                "comment": human_result.get("comment", ""),
                "is_synthetic": True
            }]
        }
        
        db.collection("nazokake_items").document(doc_ref.id).set(item_data)
        
        with open(ARCHIVE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"event_type": "legacy_import", "doc_id": doc_ref.id, "data": item_data}, ensure_ascii=False) + "\n")
        
        print(f"✅ インポート成功: ⭐{score} (偏差: {deviation})")
        return True
        
    except Exception as e:
        print(f"⚠️ エラー発生: {e}")
        return False

def import_from_csv():
    """CSVファイルから一括で読み込む"""
    if not CSV_PATH.exists():
        print(f"❌ エラー: CSVファイルが見つかりません ({CSV_PATH})")
        return

    print(f"📂 CSVファイル ({CSV_PATH.name}) を読み込みます...")
    success_count = 0
    skip_count = 0

    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            odai = row.get("お題", "").strip()
            text = row.get("完成文章", "").strip()
            
            if not odai or not text:
                continue
                
            is_success = process_import(odai, text)
            if is_success:
                success_count += 1
                time.sleep(2) # レートリミット対策
            else:
                skip_count += 1

    print(f"\n🎉 [Import] 処理完了! 成功: {success_count}件, スキップ/エラー: {skip_count}件")

if __name__ == "__main__":
    import_from_csv()

import os
import json
import re
import time
import threading
import concurrent.futures
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
ODAI_FILE_PATH = CURRENT_DIR / "odai.txt" # ⚡ マスターリストのパス

archive_lock = threading.Lock()
file_lock = threading.Lock() # ファイル操作用のロック

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

config_path = CURRENT_DIR / "backend" / "prompt_config.json"
try:
    with open(config_path, "r", encoding="utf-8") as f:
        PROMPT_CONFIG = json.load(f)
except FileNotFoundError:
    PROMPT_CONFIG = {"system_persona": "あなたは伝説的ななぞかけの名匠です。"}

def is_duplicate_in_db(word):
    """【完全重複ブロック】"""
    docs = db.collection("nazokake_items").where("A_TITLE", "==", word).limit(1).stream()
    return any(True for _ in docs)

def consume_words_from_file(count=3):
    """【完全消費型キュー】odai.txtから上から順に取得し、取得分はファイルから削除する"""
    with file_lock:
        if not ODAI_FILE_PATH.exists():
            print(f"⚠️ {ODAI_FILE_PATH.name} が見つかりません。")
            return []

        try:
            with open(ODAI_FILE_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            
            # ダブルクォーテーションの中身（お題）を全て抽出
            words = re.findall(r'"([^"]+)"', content)
            
            if not words:
                return [] # ファイルが空の場合
                
            # 上から必要な数だけ取得
            selected_words = words[:count]
            remaining_words = words[count:]
            
            # 残りの言葉でファイルを上書き保存（消費）
            with open(ODAI_FILE_PATH, "w", encoding="utf-8") as f:
                for w in remaining_words:
                    f.write(f'"{w}",\n')
                    
            return selected_words
            
        except Exception as e:
            print(f"⚠️ ファイル読み書きエラー: {e}")
            return []

def generate_nazokake_advanced(word):
    """【ステップ2】A(ファイル指定) × B(日常辞書単語) ＋ C(短文オチ)"""
    sys_persona = PROMPT_CONFIG.get("system_persona", "あなたは言葉遊びの天才です。")
    
    few_shot = """【至高の模範解答（必ずこの構造と知能レベルを真似すること）】
- 「不良少年」とかけて、「古いパソコン」と解く。その心は、どちらも『コウセイ（更生／構成）』しだいで見違えるでしょう。
- 「迷子」とかけて、「内閣総理大臣」と解く。その心は、どちらも『シジ（指示／支持）』がないと動けません。
- 「満員電車」とかけて、「下手なお笑い芸人」と解く。その心は、どちらも『スベる（物理的に滑る／ギャグがスベる）』隙間もありません。
- 「結婚式のスピーチ」とかけて、「女性のスカート」と解く。その心は、『どちらも、短いほうが喜ばれます』。"""

    prompt = f"""{sys_persona}

{few_shot}

【今回のお題（A）】: 「{word}」

【極秘ミッション: 至高のなぞかけ生成】
1. 上記の「至高の模範解答」を深く分析してください。ただの共通点ではなく、見事な「同音異義語（掛詞）」や、思わずニヤリとする「気の利いた真理」が含まれていることがわかります。
2. 日本語辞書の中から、お題「{word}」とは意味が全く異なるが、見事な掛詞で結びつく【日常会話でよく使う一般的な単語（解：B）】を選択してください。難しい言葉は避けてください。
3. 【絶対ルール】「その心は（C）」はダラダラと説明せず、模範解答のように短いフレーズ（短文）でスパッと落としてください。

【必ず以下のJSONのみ出力】
{{
  "nazokake_text": "「〇〇」とかけて、「〇〇」と解く。その心は...",
  "selected_homonym": "選んだ言葉や共通点の解説",
  "reasoning": "なぜこの組み合わせが模範解答レベルで秀逸なのか"
}}"""
    
    response = client.models.generate_content(
        model='gemini-3-flash-preview', # ⚡ 確実に動く安定モデル
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.9)
    )
    return json.loads(re.search(r'\{.*\}', response.text.strip(), re.DOTALL).group(0))

def simulate_human_eval(word, nazokake_text):
    prompt = f"""あなたはなぞかけの審美眼を持つベテラン観客です。
以下の日常なぞかけを評価してください。
- 星5: 傑作。見事なダブルミーニング（同音異義語）、または思わず膝を打つ秀逸な共通点がある。オチの文章も短い。
- 星4: 秀作。テンポが良く、言葉遊びとして成立している。
- 星3: 凡作。ただの共通点であり、掛詞になっていない。またはオチが長すぎる。
- 星1-2: 失敗。意味が通じない。

お題: {word}
なぞかけ: {nazokake_text}

【必ず以下のJSONのみ出力】
{{"star_score": 5, "comment": "寸評"}}"""
    
    response = client.models.generate_content(
        model='gemini-3-flash-preview', 
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2)
    )
    return json.loads(re.search(r'\{.*\}', response.text.strip(), re.DOTALL).group(0))

def process_single_mission(word):
    try:
        if is_duplicate_in_db(word):
            return None, word, "🔄 過去のお題（DB重複）のためスキップしました"

        result = generate_nazokake_advanced(word)
        eval_result = simulate_human_eval(word, result["nazokake_text"])
        score = eval_result.get("star_score", 3)
        
        if score < 4:
            return score, word, f"不合格(⭐{score})につき破棄"
        
        doc_ref = db.collection("nazokake_items").document()
        now_str = datetime.now().isoformat()
        
        item_data = {
            "A_TITLE": word,
            "nazokake_text": result["nazokake_text"],
            "scores": {"S_total": score/5},
            "reasoning": result.get("reasoning", ""),
            "status": "completed",
            "created_at": now_str,
            "is_golden": False,
            "author": "AI_Agent_MasterQueue_v14", 
            "user_evaluations": [{
                "timestamp": now_str,
                "user_score": score,
                "comment": eval_result.get("comment", ""),
                "is_synthetic": True
            }]
        }
        
        doc_ref.set(item_data)
        
        with archive_lock:
            with open(ARCHIVE_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps({"event_type": "auto_agent_masterqueue_v14", "doc_id": doc_ref.id, "data": item_data}, ensure_ascii=False) + "\n")
        
        return score, word, result['nazokake_text']
        
    except Exception as e:
        return None, word, f"⚠️ 通信エラー: {str(e)[:100]}"

def run_mission_loop(batch_size=3):
    print(f"🚀 [RLAIF Agent v8-14 Master Queue] リスト完全消費ファクトリー ＋ 10秒インターバル")
    
    mission_count = 1
    while True:
        print(f"\n================ 🔄 ミッション {mission_count} ================")
        
        # ⚡ リストから消費（取得＆削除）
        words = consume_words_from_file(batch_size)
        
        if not words:
            print(f"🎉 【完了】odai.txt のお題を全て消化しました！自動的に終了します。")
            break
            
        print(f"📡 ターゲット(残弾消費中): {words}")
        
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        futures = []
        for w in words:
            futures.append(executor.submit(process_single_mission, w))
            time.sleep(2) # APIの同時リクエスト制限回避
        
        try:
            for future in concurrent.futures.as_completed(futures, timeout=90):
                score, word, output = future.result()
                if score is None:
                    print(f"⏭️  【スルー】 ({word}) -> {output}")
                elif score >= 4:
                    print(f"👑 【傑作 ⭐{score}】 ({word}) -> {output}")
                else:
                    print(f"🗑️  【破棄 ⭐{score}】 ({word}) -> {output}")
        except concurrent.futures.TimeoutError:
            print("⚠️ 【タイムアウト発生】APIからの応答が途絶えました。見切りをつけて次へ進みます。")
        
        executor.shutdown(wait=False, cancel_futures=True)
                
        print("⏳ 次のミッションまで【10秒間】待機します...")
        time.sleep(10)
        mission_count += 1

if __name__ == "__main__":
    run_mission_loop(batch_size=3)

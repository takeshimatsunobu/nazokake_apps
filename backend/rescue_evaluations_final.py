import sys
import os
import glob
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import google.generativeai as genai

# ==========================================
# 1. FirebaseとGeminiの初期化
# ==========================================
# 鍵ファイルの探索
key_files = glob.glob("*firebase-adminsdk*.json") + glob.glob("../*firebase-adminsdk*.json")
if not key_files:
    print("🚨 JSON鍵ファイルが見つかりません。")
    sys.exit()

try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(key_files[0])
        firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"初期化エラー: {e}")
    sys.exit()

db = firestore.client()
collection_name = "nazokake_items"

# 環境変数からGemini APIキーを取得（設定されていない場合はエラー）
gemini_api_key = os.environ.get("GEMINI_API_KEY")
if not gemini_api_key:
    # .env ファイルから直接読み取る試み
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("GEMINI_API_KEY="):
                    gemini_api_key = line.strip().split("=")[1]
                    break
    except: pass

if not gemini_api_key:
    print("🚨 エラー: GEMINI_API_KEY が見つかりません。")
    sys.exit()

genai.configure(api_key=gemini_api_key)
# モデルはGemini 1.5 Flashを使用（高速で安定しているため救済処理に最適）
model = genai.GenerativeModel("gemini-1.5-flash")

# ==========================================
# 2. 評価ロジックを直接埋め込む（絶対に迷子にならない！）
# ==========================================
def evaluate_nazokake_direct(odai: str, nazokake_text: str):
    prompt = f"""
    あなたは「なぞかけ」のプロフェッショナル審査員です。
    以下のお題と作品を評価し、JSON形式で出力してください。

    【お題】: {odai}
    【作品】: {nazokake_text}

    出力形式:
    {{
        "scores": {{
            "S_sur": 0.0〜1.0の数値 (意外性),
            "S_tech": 0.0〜1.0の数値 (技巧性),
            "S_emo": 0.0〜1.0の数値 (納得感),
            "S_rhy": 0.0〜1.0の数値 (テンポ・リズム),
            "S_humor": 0.0〜1.0の数値 (ユーモア),
            "S_visual": 0.0〜1.0の数値 (情景),
            "S_cultural": 0.0〜1.0の数値 (文化),
            "S_prosody": 0.0〜1.0の数値 (韻律),
            "S_cm": 0.0〜1.0の数値 (比喩),
            "S_ontology": 0.0〜1.0の数値 (存在論),
            "S_sensory": 0.0〜1.0の数値 (感覚)
        }},
        "reasoning": "審査講評を100文字程度で記述"
    }}
    JSON以外のテキストは絶対に出力しないでください。
    """
    
    response = model.generate_content(prompt)
    response_text = response.text.strip()
    
    # Markdownのコードブロック(```json ... ```)を削除
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.startswith("```"):
        response_text = response_text[3:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]
        
    result_dict = json.loads(response_text.strip())
    
    # 総合点の計算
    scores = result_dict.get("scores", {})
    total = sum(float(v) for v in scores.values())
    s_total = round((total / 11.0) * 5.0, 2) # 5点満点に換算
    
    result_dict["s_total"] = s_total
    return result_dict

# ==========================================
# 3. 評価待ちのデータを全て呼び起こして救済する
# ==========================================
print("\n🔍 評価待ち（processing）のデータを検索中...")
docs = db.collection(collection_name).where(filter=FieldFilter("eval_status", "==", "processing")).stream()

rescue_count = 0
for doc in docs:
    data = doc.to_dict()
    odai = data.get("A_TITLE", "不明")
    text = data.get("nazokake_text", "")
    
    print(f"🔄 救済中（再評価）: 【{odai}】...")
    try:
        # 埋め込んだAI評価を直接実行
        result = evaluate_nazokake_direct(odai, text)
                
        # データベースを更新
        db.collection(collection_name).document(doc.id).update({
            "scores": result["scores"],
            "s_total": result.get("s_total", 0),
            "eval_reasoning": result.get("reasoning", "講評の取得に失敗しました。"),
            "reasoning": result.get("reasoning", "講評の取得に失敗しました。"),
            "eval_status": "completed",
            "status": "completed",
            "evaluated_at": firestore.SERVER_TIMESTAMP
        })
        
        print(f"  └ ✅ 処理完了！ (総合点: {result.get('s_total', 0)})")
        rescue_count += 1
    except Exception as e:
        print(f"  └ ❌ エラー: {e}")
        
print(f"\n🎉 処理完了！ 合計 {rescue_count} 件のなぞかけを救済しました！")

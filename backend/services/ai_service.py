import requests
import json
import os
import re
from firebase_admin import firestore
from google import genai
from google.genai.types import GenerateContentConfig

# --- 設定 ---
VM_IP = "100.70.53.71"
TIER1_URL = f"http://{VM_IP}:8080/v1/chat/completions"
TIER2_URL = f"http://{VM_IP}:8081/v1/chat/completions"

EVALUATOR_MODEL = os.environ.get("EVALUATOR_MODEL_NAME", "gemini-3.1-pro-preview")
GENERATOR_FALLBACK = os.environ.get("GENERATOR_FALLBACK_MODEL", "gemini-3-flash-preview")

# 💡 要塞がオフの時は無駄なタイムアウトを即座にスキップする直通スイッチ
USE_LOCAL_GCP = os.environ.get("USE_LOCAL_GCP", "false").lower() == "true"

def chat_completion_local(url, system_prompt, user_prompt, max_tokens=256, temperature=0.8):
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.9
    }
    # 🚨 ここを強制的に 3.0 秒に修正！
    res = requests.post(url, json=payload, timeout=3.0)
    res.raise_for_status()
    return res.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()

def generate_nazokake(odai: str):
    # 🔥 修正: 「とく」の部分に対する文字数と品詞の絶対制約を追加
    sys_prompt = "あなたは前衛的な天才なぞかけ芸人です。\n【重要】提供される例や過去のコンテキストは「型」の参考のみとし、言葉や内容は絶対にコピーせず100%オリジナルの発想で出力してください。\n\n【思考プロセス】\n1. お題(A)から連想される言葉を挙げる。\n2. その言葉と同じ「ひらがな」で、全く別の意味を持つ言葉(B)を探す。\n3. (B)から連想される、お題と無関係なジャンルの言葉を「とく(××)」にする。\n【絶対制約】「××ととく」の「××」は、絶対に10文字以内の短い単語（名詞など）にしてください。説明的な長文は即座に失格とします。\n\n【出力フォーマット】（必ずこの通りに出力）\n【思考】\n1. 連想: \n2. 同音異義語: \n3. とくの決定: \n\n【なぞかけ】\n〇〇とかけて、\n××ととく。\nそのこころは、\n□□でしょう。"
    user_prompt = f"お題「{odai}」で、思考プロセスを踏まえて見事ななぞかけを作成してください。"
    
    raw_result = ""
    if USE_LOCAL_GCP:
        try:
            print("🔍 GCP要塞へ接続を試みます...")
            raw_result = chat_completion_local(TIER1_URL, sys_prompt, user_prompt, max_tokens=250, temperature=0.8)
        except Exception as conn_err_1:
            print(f"⚠️ GCP要塞が無応答({conn_err_1})。フォールバックします。")
    
    if not raw_result:
        print("☁️ クラウドGeminiで生成します...")
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        full_prompt = f"{sys_prompt}\n\n{user_prompt}"
        res_create = client.models.generate_content(
            model=GENERATOR_FALLBACK, 
            contents=full_prompt, 
            config=GenerateContentConfig(temperature=0.8)
        )
        raw_result = res_create.text
        
    if "【なぞかけ】" in raw_result:
        return raw_result.split("【なぞかけ】")[-1].strip()
    return raw_result.strip()

def evaluate_and_update_task(db: firestore.client, doc_id: str, odai: str, nazokake_text: str):
    doc_ref = db.collection("nazokake_items").document(doc_id)
    try:
        doc = doc_ref.get()
        if doc.exists and doc.to_dict().get("eval_status") == "completed": 
            return
        
        ctx_sys = "あなたは日本の現代カルチャーに精通したエージェントです。事実と文脈だけを簡潔に出力してください。"
        ctx_user = f"お題「{odai}」となぞかけ「{nazokake_text}」の同音異義語と文化的背景を解説してください。"
        context_text = ""
        
        if USE_LOCAL_GCP:
            try:
                print("🔍 GCP要塞で文化背景の抽出を試みます...")
                context_text = chat_completion_local(TIER2_URL, ctx_sys, ctx_user, max_tokens=300, temperature=0.3)
            except Exception as conn_err_2:
                print(f"⚠️ 文化背景抽出スキップ: {conn_err_2}")
                
        if not context_text: 
            context_text = "※直通モードのため文化背景の自動抽出なし"

        judge_sys = "あなたは最高峰の採点AIシステムです。\n以下の11項目の評価軸（0.0〜1.0）でなぞかけを評価し、結果をJSONフォーマット【のみ】で出力してください。Markdown装飾（バッククォート3つのjson等）は絶対に使用しないでください。\n\n{\n  \"scores\": {\n    \"S_sur\": 0.0, \"S_tech\": 0.0, \"S_emo\": 0.0, \"S_rhy\": 0.0, \"S_sensory\": 0.0, \n    \"S_visual\": 0.0, \"S_ontology\": 0.0, \"S_cultural\": 0.0, \"S_cm\": 0.0, \"S_prosody\": 0.0, \"S_nat\": 0.0\n  },\n  \"reasoning\": \"ここに200文字以内で講評を記述\"\n}"
        judge_user = f"以下のなぞかけと文化背景を元に、JSONフォーマットのみで評価を出力してください。\n\n【なぞかけ】\n{nazokake_text}\n\n【文化背景】\n{context_text}\n\n結果（JSONのみ）:"
        raw_result = ""
        
        if USE_LOCAL_GCP:
            try:
                print("🔍 GCP要塞で評価を試みます...")
                raw_result = chat_completion_local(TIER2_URL, judge_sys, judge_user, max_tokens=600, temperature=0.1)
            except Exception as conn_err_3:
                print(f"⚠️ 評価スキップ: {conn_err_3}")
                
        if not raw_result:
            print("☁️ クラウドGeminiで評価します...")
            client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
            full_judge_prompt = f"{judge_sys}\n\n{judge_user}"
            res_eval = client.models.generate_content(
                model=EVALUATOR_MODEL, 
                contents=full_judge_prompt, 
                config=GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
            )
            raw_result = res_eval.text

        eval_data = {}
        try:
            cleaned_result = re.sub(r'```json\n?|```\n?', '', raw_result).strip()
            match = re.search(r'\{.*\}', cleaned_result, re.DOTALL)
            if match: 
                eval_data = json.loads(match.group(0))
            else: 
                raise ValueError("JSON形式が見つかりません")
        except Exception as parse_err:
            doc_ref.update({"status": -1, "eval_status": "error", "error_msg": f"AIの評価フォーマットエラー: {parse_err}"})
            return 

        scores = eval_data.get("scores", {})
        final_scores = {k: float(scores.get(k, 0.5)) for k in ["S_sur", "S_tech", "S_emo", "S_rhy", "S_sensory", "S_visual", "S_ontology", "S_cultural", "S_cm", "S_prosody", "S_nat"]}
        s_total = (sum(final_scores.values()) / 11.0) * 5.0

        doc_ref.update({
            "eval_status": "completed", 
            "status": 2, 
            "context_extracted": context_text, 
            "scores": final_scores, 
            "s_total": s_total, 
            "reasoning": eval_data.get("reasoning", "講評が取得できませんでした。"), 
            "evaluated_at": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        doc_ref.update({"status": -1, "eval_status": "error", "error_msg": str(e)})

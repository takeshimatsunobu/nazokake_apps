import json
import os
import re
import asyncio
import httpx
from firebase_admin import firestore
from google import genai
from google.genai.types import GenerateContentConfig

# ==========================================
# 🛡️ 構造化出力（Structured Outputs）の辞書型スキーマ定義（SDK完全互換）
# ==========================================
nazokake_schema = {
    "type": "OBJECT",
    "properties": {
        "hint": {"type": "STRING", "description": "AIの思考プロセス、連想したことの解説"},
        "toku": {"type": "STRING", "description": "短い単語（例：打率）"},
        # 🚨 修正: 「どちらも〜でしょう」の縛りを完全に撤廃し、AIに自由な表現を許可
        "kokoro": {"type": "STRING", "description": "落ちの文章。必ずしも「〜でしょう」で終わる必要はなく、「〜が欠かせません」「〜で決まります」など、最も自然で面白い結びの言葉にすること。"}
    },
    "required": ["hint", "toku", "kokoro"]
}

evaluation_schema = {
    "type": "OBJECT",
    "properties": {
        "scores": {
            "type": "OBJECT",
            "properties": {
                "S_sur": {"type": "NUMBER"}, "S_tech": {"type": "NUMBER"},
                "S_emo": {"type": "NUMBER"}, "S_rhy": {"type": "NUMBER"},
                "S_sensory": {"type": "NUMBER"}, "S_visual": {"type": "NUMBER"},
                "S_ontology": {"type": "NUMBER"}, "S_cultural": {"type": "NUMBER"},
                "S_cm": {"type": "NUMBER"}, "S_prosody": {"type": "NUMBER"},
                "S_nat": {"type": "NUMBER"}
            },
            "required": ["S_sur", "S_tech", "S_emo", "S_rhy", "S_sensory", "S_visual", "S_ontology", "S_cultural", "S_cm", "S_prosody", "S_nat"]
        },
        "reasoning": {"type": "STRING"}
    },
    "required": ["scores", "reasoning"]
}

# --- 設定 ---
VM_IP = os.environ.get("GCP_L4_IP", "")
TIER1_URL = f"http://{VM_IP}:8080/v1/chat/completions" if VM_IP else ""
TIER2_URL = f"http://{VM_IP}:8081/v1/chat/completions" if VM_IP else ""

EVALUATOR_MODEL = os.environ.get("EVALUATOR_MODEL_NAME", "gemini-1.5-pro") # 最新モデルに更新
GENERATOR_FALLBACK = os.environ.get("GENERATOR_FALLBACK_MODEL", "gemini-1.5-flash") # 最新モデルに更新

_use_local = os.environ.get("USE_LOCAL_GCP", "false").lower() == "true"
USE_LOCAL_GCP = _use_local and bool(VM_IP)

async def chat_completion_local(url, system_prompt, user_prompt, max_tokens=256, temperature=0.8):
    if not url:
        raise ValueError("VM_IPが設定されていません。")
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.9
    }
    async with httpx.AsyncClient(timeout=3.0) as client:
        res = await client.post(url, json=payload)
        res.raise_for_status()
        return res.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()

async def generate_nazokake(odai: str) -> dict:
    db = firestore.client()
    dyn_temp = 0.8
    dyn_model = GENERATOR_FALLBACK
    dyn_persona = "あなたは前衛的な天才なぞかけ芸人です。"
    
    try:
        config_doc = db.collection("system_configs").document("ai_settings").get()
        if config_doc.exists:
            c_data = config_doc.to_dict()
            dyn_temp = float(c_data.get("temperature", 0.8))
            dyn_model = c_data.get("model_name", GENERATOR_FALLBACK)
            dyn_persona = c_data.get("system_prompt", dyn_persona)
    except Exception as e:
        print(f"⚠️ 動的設定の取得に失敗しました。デフォルト値を使用します: {e}")

    # 🚨 修正: プロンプトで「定型文の禁止」と「自然な日本語」を強制
    sys_prompt = f"""{dyn_persona}
【重要】提供される例は「型」の参考のみとし、言葉や内容は絶対にコピーせず100%オリジナルの発想で出力してください。

【思考プロセス】
1. お題(A)から連想される言葉を挙げる。
2. その言葉と同じ「ひらがな」で、全く別の意味を持つ言葉(B)を探す。
3. (B)から連想される言葉を「とく(××)」にする。

【絶対制約】
・「××ととく」の「××」は絶対に10文字以内の短い単語にしてください。
・落ちの文章（こころ）は、「〜でしょう」という定型文に縛られず、文脈に合わせて最も自然で面白い日本語で結んでください。"""
    
    user_prompt = f"お題「{odai}」でなぞかけを作成してください。"
    
    raw_result = ""
    if USE_LOCAL_GCP:
        try:
            print(f"🔍 GCP要塞へ接続を試みます... (Temp: {dyn_temp})")
            raw_result = await chat_completion_local(TIER1_URL, sys_prompt, user_prompt, max_tokens=250, temperature=dyn_temp)
        except Exception as conn_err_1:
            print(f"⚠️ GCP要塞が無応答({conn_err_1})。フォールバックします。")
    
    if not raw_result:
        print(f"☁️ クラウドGeminiで生成します... (Model: {dyn_model}, Temp: {dyn_temp})")
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        full_prompt = f"{sys_prompt}\n\n{user_prompt}"
        res_create = await client.aio.models.generate_content(
            model=dyn_model, 
            contents=full_prompt, 
            config=GenerateContentConfig(
                response_mime_type="application/json", 
                response_schema=nazokake_schema,
                temperature=dyn_temp
            )
        )
        raw_result = res_create.text
        
    try:
        cleaned_result = re.sub(r'```json\n?|```\n?', '', raw_result).strip()
        match = re.search(r'\{.*\}', cleaned_result, re.DOTALL)
        if match: 
            return json.loads(match.group(0))
        else: 
            return json.loads(cleaned_result)
    except Exception as e:
        print(f"解析エラー: {e}")
        raise ValueError(f"AIがJSONフォーマットを守りませんでした。生成を中断します。(詳細: {e})")

async def evaluate_and_update_task(db, doc_id: str, odai: str, nazokake_text: str):
    doc_ref = db.collection("nazokake_items").document(doc_id)
    try:
        doc = await asyncio.to_thread(doc_ref.get)
        if doc.exists and doc.to_dict().get("eval_status") == "completed": 
            return
        
        ctx_sys = "あなたは日本の現代カルチャーに精通したエージェントです。事実と文脈だけを簡潔に出力してください。"
        ctx_user = f"お題「{odai}」となぞかけ「{nazokake_text}」の同音異義語と文化的背景を解説してください。"
        context_text = ""
        
        if USE_LOCAL_GCP:
            try:
                print("🔍 GCP要塞で文化背景の抽出を試みます...")
                context_text = await chat_completion_local(TIER2_URL, ctx_sys, ctx_user, max_tokens=300, temperature=0.3)
            except Exception as conn_err_2:
                print(f"⚠️ 文化背景抽出スキップ: {conn_err_2}")
                
        if not context_text: 
            context_text = "※直通モードのため文化背景の自動抽出なし"

        judge_sys = "あなたは最高峰の採点AIシステムです。\n以下の11項目の評価軸（0.0〜1.0）でなぞかけを評価してください。"
        judge_user = f"以下のなぞかけと文化背景を元に評価を出力してください。\n\n【なぞかけ】\n{nazokake_text}\n\n【文化背景】\n{context_text}"
        raw_result = ""
        
        if USE_LOCAL_GCP:
            try:
                print("🔍 GCP要塞で評価を試みます...")
                raw_result = await chat_completion_local(TIER2_URL, judge_sys, judge_user, max_tokens=600, temperature=0.1)
            except Exception as conn_err_3:
                print(f"⚠️ 評価スキップ: {conn_err_3}")
                
        if not raw_result:
            print("☁️ クラウドGeminiで評価します...")
            client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
            full_judge_prompt = f"{judge_sys}\n\n{judge_user}"
            res_eval = await client.aio.models.generate_content(
                model=EVALUATOR_MODEL, 
                contents=full_judge_prompt, 
                config=GenerateContentConfig(
                    response_mime_type="application/json", 
                    response_schema=evaluation_schema,
                    temperature=0.1
                )
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
            await asyncio.to_thread(doc_ref.update, {"status": "error", "eval_status": "error", "message": f"AIの評価フォーマットエラー: {parse_err}"})
            return 

        scores = eval_data.get("scores", {})
        final_scores = {k: float(scores.get(k, 0.5)) for k in ["S_sur", "S_tech", "S_emo", "S_rhy", "S_sensory", "S_visual", "S_ontology", "S_cultural", "S_cm", "S_prosody", "S_nat"]}
        s_total = (sum(final_scores.values()) / 11.0) * 5.0

        await asyncio.to_thread(doc_ref.update, {
            "eval_status": "completed", 
            "status": "completed", 
            "context_extracted": context_text, 
            "scores": final_scores, 
            "s_total": s_total, 
            "reasoning": eval_data.get("reasoning", "講評が取得できませんでした。"), 
            "message": "生成・鑑定が完了しました！",
            "evaluated_at": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        await asyncio.to_thread(doc_ref.update, {"status": "error", "eval_status": "error", "message": f"システムエラー: {str(e)}"})

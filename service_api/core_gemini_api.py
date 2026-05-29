import os
import json
import time
import google.generativeai as genai
from dotenv import load_dotenv
from backend.prompts import EVALUATION_SYSTEM_PROMPT, build_user_prompt

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

def evaluate_nazokake(a: str, b: str, c: str, detail: str, g_type: str, text: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    model_name = os.environ.get("GEMINI_MODEL")
    if not api_key or not model_name:
        raise ValueError(".envのAPIキーまたはモデル名が不足しています。")

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name=model_name, system_instruction=EVALUATION_SYSTEM_PROMPT)
        user_prompt = build_user_prompt(a, b, c, detail, g_type, text)
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = model.generate_content(
                    user_prompt,
                    generation_config=genai.GenerationConfig(response_mime_type="application/json", temperature=0.2),
                    request_options={"timeout": 120}
                )
                
                raw_text = response.text.strip()
                
                # コピペエラーを防ぐため、文字列の指定をシングルクォーテーションに統一
                if raw_text.startswith('```json'):
                    raw_text = raw_text[7:]
                elif raw_text.startswith('```'):
                    raw_text = raw_text[3:]
                    
                if raw_text.endswith('```'):
                    raw_text = raw_text[:-3]
                
                return json.loads(raw_text.strip())
                
            except Exception as e:
                error_msg = str(e).lower()
                if "504" in error_msg or "429" in error_msg or "quota" in error_msg or "timed out" in error_msg or "cancelled" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = 15 * (attempt + 1)
                        if attempt == 2: wait_time = 60
                        print(f"    ⚠️ サーバー混雑中。{wait_time}秒後に再試行します...（{attempt+1}/{max_retries}回目）")
                        time.sleep(wait_time)
                        continue
                raise e
    finally:
        pass
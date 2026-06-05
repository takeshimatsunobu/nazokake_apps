import requests
import time
import traceback
import re
import os
from dotenv import load_dotenv

load_dotenv()

try:
    from google import genai
    from google.genai.types import GenerateContentConfig
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

class DualAIRouter:
    def __init__(self, tier1_url="http://localhost:8080", tier2_url="http://localhost:8081"):
        self.tier1_url = tier1_url
        self.tier2_url = tier2_url
        self.gemini_client = None
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if HAS_GENAI and api_key:
            self.gemini_client = genai.Client(api_key=api_key)

    def generate_chat(self, system_prompt: str, user_prompt: str, tier: int = 1, max_tokens: int = 256, temperature: float = 0.7):
        target_url = self.tier1_url if tier == 1 else self.tier2_url
        endpoint = f"{target_url}/v1/chat/completions"
        
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        
        print(f"🔄 [LLM_ROUTER] Tier {tier} (Local: {target_url}) へ接続を試みます...")
        
        # --- 🛡️ 防弾フェーズ1: ローカル接続（失敗したら全て握りつぶす） ---
        local_success = False
        try:
            # タイムアウトを3秒に設定（待たせない）
            response = requests.post(endpoint, json=payload, timeout=3.0)
            response.raise_for_status()
            local_success = True
            
            print(f"✅ [LLM_ROUTER] Local AI 応答成功！")
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            content = re.sub(r'<\|.*?\|>', '', content).strip()
            return {"text": content, "error": None, "source": "local"}
            
        except Exception as e:
            # WinError 10061 を含む、あらゆるエラーをここでキャッチ
            print(f"⚠️ [LLM_ROUTER] Local AI 応答なし (理由: {type(e).__name__})。クラウド(Gemini)へフォールバックします！")
            
        # --- ☁️ 防弾フェーズ2: クラウドへの自動旋回 ---
        if not local_success:
            return self._fallback_to_cloud(system_prompt, user_prompt, temperature)

    def _fallback_to_cloud(self, system_prompt: str, user_prompt: str, temperature: float):
        if not self.gemini_client:
            return {"error": "LOCAL_OFFLINE_AND_NO_API_KEY", "raw": "ローカルAIがダウンしており、かつAPIキーが未設定です。"}
            
        try:
            full_prompt = f"{system_prompt}\n\n{user_prompt}"
            res = self.gemini_client.models.generate_content(
                model="gemini-3.5-flash", # ファクトベースで選定した最新・最速モデル
                contents=full_prompt,
                config=GenerateContentConfig(temperature=temperature)
            )
            print("☁️ [LLM_ROUTER] クラウド(Gemini 3.5 Flash)での生成が完了しました！")
            return {"text": res.text, "error": None, "source": "cloud"}
        except Exception as e:
            return {"error": f"CLOUD_FALLBACK_FAILED: {str(e)}", "raw": traceback.format_exc(), "location": "CloudFallback"}

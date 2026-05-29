import requests
import time
import traceback
import re

class DualAIRouter:
    def __init__(self, tier1_url="http://localhost:8080", tier2_url="http://localhost:8081"):
        self.tier1_url = tier1_url
        self.tier2_url = tier2_url

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
        
        start_time = time.time()
        print(f"[LLM_TRACE] [Phase: Init] Sending Chat Request to Tier {tier}")
        
        try:
            response = requests.post(endpoint, json=payload, timeout=45.0)
            elapsed = time.time() - start_time
            print(f"[LLM_TRACE] [Phase: Connected] Status: {response.status_code} in {elapsed:.2f}s")
            
            if response.status_code != 200:
                return {"error": f"HTTP_{response.status_code}", "raw": response.text, "location": "ServerResponse"}
                
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            
            # 🧹 特殊なストップトークン（ノイズ）を強制クリーニング
            content = re.sub(r'<\|.*?\|>', '', content).strip()
            
            return {"text": content, "error": None}
                
        except requests.exceptions.Timeout:
            return {"error": "REQUEST_TIMEOUT_45SEC", "raw": None, "location": "NetworkConnection"}
        except Exception as e:
            return {"error": f"UNEXPECTED: {str(e)}", "raw": traceback.format_exc(), "location": "UnknownInternal"}

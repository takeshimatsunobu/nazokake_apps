import json
import google.generativeai as genai

try:
    with open("gemini_api_key.json", "r") as f:
        api_key = json.load(f).get("api_key")
    
    genai.configure(api_key=api_key)
    
    print("\n🔍 【スキャン結果】 あなたのAPIキーで利用可能なモデル一覧:")
    for m in genai.list_models():
        if "generateContent" in m.supported_generation_methods:
            print(f" - {m.name}")
    print("\n")
except Exception as e:
    print(f"🚨 エラーが発生しました: {e}")

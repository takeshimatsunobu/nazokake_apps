import os
from google import genai

API_KEY = "AIzaSyDVly4bOMt6KnsuTbm3QHLT4WiqkNH9_Ng"

print("="*50)
print("🔍 あなたのAPIキーで利用可能な Gemini Flash/Pro モデルを検索中...")
print("="*50)

try:
    client = genai.Client(api_key=API_KEY)
    # 修正: 新SDKの正しいメソッド名 list() を使用
    models = client.models.list()
    found = False
    for m in models:
        if "flash" in m.name.lower() or "pro" in m.name.lower():
            print(f"✅ {m.name}")
            found = True
    if not found:
        print("⚠️ 該当するモデルが見つかりませんでした。")
except Exception as e:
    print(f"🚨 API通信エラー: {e}")
print("="*50)

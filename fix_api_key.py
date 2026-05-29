import os

file_path = 'backend/main.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

old_code = '''try:
    with open('gemini_api_key.json', 'r') as f:
        api_data = json.load(f)
        genai.configure(api_key=api_data['api_key'])
    logger.info("💎 Gemini API configured successfully.")
except Exception as e:
    logger.error(f"🚨 Gemini config error: {e}")'''

new_code = '''try:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and os.path.exists('gemini_api_key.json'):
        with open('gemini_api_key.json', 'r') as f:
            api_data = json.load(f)
            api_key = api_data.get('api_key')
    
    if api_key:
        genai.configure(api_key=api_key)
        logger.info("💎 Gemini API configured successfully.")
    else:
        logger.warning("⚠️ GEMINI_API_KEY が見つかりません。環境変数を設定するか、gemini_api_key.json を配置してください。")
except Exception as e:
    logger.error(f"🚨 Gemini config error: {e}")'''

content = content.replace(old_code, new_code)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ main.py の Gemini API読み込み設定を修正しました！")

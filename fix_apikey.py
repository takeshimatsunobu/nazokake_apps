import os
import re

file_path = r"service_frontend\pages\2_admin_settings.py"

if os.path.exists(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # dotenvのインポートと読み込み処理を追加
    import_addition = """import os
from dotenv import load_dotenv
load_dotenv() # .envファイルからAPIキーを読み込む
"""
    
    if "from dotenv import load_dotenv" not in content:
        content = content.replace("import os\n", import_addition)

    # APIキーの取得方法を修正
    old_api_code = 'api_key = os.environ.get("GEMINI_API_KEY")'
    new_api_code = """api_key = os.environ.get("GEMINI_API_KEY")
                if not api_key:
                    st.error("🚨 サーバーエラー: GEMINI_API_KEY が設定されていません（.envファイルを確認してください）")
                    st.stop()"""
    
    content = content.replace(old_api_code, new_api_code)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    print("✅ 2_admin_settings.py にAPIキー読み込みパッチを適用しました！")
else:
    print("❌ ファイルが見つかりません。")

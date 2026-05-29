import os
import re

files_to_fix = [
    r"service_frontend\ui_main.py",
    r"service_frontend\pages\1_dashboard.py",
    r"service_frontend\pages\2_admin_settings.py"
]

for file_path in files_to_fix:
    if not os.path.exists(file_path):
        continue
        
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. 古い backend へのパスを service_worker に書き換え
    content = content.replace("from backend.gemini_api import", "from service_worker.worker_gemini_api import")
    content = content.replace("import backend.gemini_api", "import service_worker.worker_gemini_api")
    
    # 2. 古い SDK を 新しい SDK の記述に書き換え
    content = content.replace("import google.generativeai as genai", "from google import genai")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
        
print("✅ フロントエンドのインポートエラーを修正するパッチを適用しました！")

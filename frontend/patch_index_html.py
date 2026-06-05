import re
import sys

file_path = "web/index.html"
try:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 古いJSとCSSの読み込みタグを正規表現で完全削除
    cleaned_content = re.sub(r'<script.*?src=["\'].*?app_final\.js.*?["\'].*?></script>\n?', '', content, flags=re.IGNORECASE)
    cleaned_content = re.sub(r'<link.*?href=["\'].*?style\.css.*?["\'].*?>\n?', '', cleaned_content, flags=re.IGNORECASE)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(cleaned_content)
    
    print("✅ [SUCCESS] index.html から不要なタグの除去に成功しました！")
except Exception as e:
    print(f"🚨 [ERROR] {e}")
    sys.exit(1)

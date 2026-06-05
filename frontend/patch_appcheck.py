import re
import sys

file_path = "lib/main.dart"
try:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 正規表現で古い FirebaseAppCheck のブロックを正確に捕捉して置換
    pattern = re.compile(r"await\s+FirebaseAppCheck\.instance\.activate\s*\([^)]+\);", re.DOTALL)
    
    new_block = """await FirebaseAppCheck.instance.activate(
    webProvider: ReCaptchaEnterpriseProvider('YOUR_RECAPTCHA_SITE_KEY'),
    androidProvider: AndroidProvider.debug,
    appleProvider: AppleProvider.debug,
  );"""

    if pattern.search(content):
        new_content = pattern.sub(new_block, content)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("✅ [SUCCESS] main.dart の AppCheck Web対応パッチを適用しました！")
    else:
        print("⚠️ [SKIP] 置換対象が見つかりません。既に修正されているか、形式が異なります。")

except Exception as e:
    print(f"🚨 [ERROR] パッチ適用失敗: {e}")
    sys.exit(1)

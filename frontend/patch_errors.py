import re
import sys

file_main = "lib/main.dart"
try:
    with open(file_main, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. kIsWeb (Web判定ツール) のインポートを追加
    if "package:flutter/foundation.dart" not in content:
        content = content.replace("import 'package:flutter/material.dart';", "import 'package:flutter/material.dart';\nimport 'package:flutter/foundation.dart';")

    # 2. AppCheckのWeb400エラーを回避 (Webならスキップするロジックに変更)
    pattern = re.compile(r"await\s+FirebaseAppCheck\.instance\.activate\(.*?\);", re.DOTALL)
    new_appcheck = """// Web版ではダミーキーによる400エラーを防ぐためAppCheckをスキップ
  if (!kIsWeb) {
    await FirebaseAppCheck.instance.activate(
      androidProvider: AndroidProvider.debug,
      appleProvider: AppleProvider.debug,
    );
  }"""
    content = pattern.sub(new_appcheck, content)

    # 3. フォント警告の抑制 (システムフォントをフォールバックに指定)
    if "fontFamilyFallback" not in content:
        content = content.replace("scaffoldBackgroundColor:", "fontFamilyFallback: const ['Hiragino Sans', 'Meiryo', 'sans-serif'],\n        scaffoldBackgroundColor:")

    with open(file_main, "w", encoding="utf-8") as f:
        f.write(content)
    
    print("✅ [SUCCESS] エラー撲滅パッチの適用に成功しました！")
except Exception as e:
    print(f"🚨 [ERROR] 予期せぬエラー: {e}")
    sys.exit(1)

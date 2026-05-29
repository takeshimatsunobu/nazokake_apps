import os
import re

print("🔍 `submit_human_nazokake` が書かれたファイルを探しています...")

target_file = None
for root, dirs, files in os.walk("."):
    if ".venv" in root or "__pycache__" in root:
        continue
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    if "def submit_human_nazokake" in f.read():
                        target_file = path
                        break
            except:
                pass
    if target_file:
        break

if not target_file:
    print("🚨 エラー: 対象のファイルが見つかりません。")
    exit()

print(f"🎯 対象ファイルを発見しました: {target_file}")

with open(target_file, "r", encoding="utf-8") as f:
    content = f.read()

# 1. BackgroundTasks 引数を削除
content = re.sub(r",\s*background_tasks:\s*BackgroundTasks", "", content)
content = re.sub(r"background_tasks:\s*BackgroundTasks\s*,?", "", content)

# 2. background_tasks.add_task を直接実行（冬眠させない処理）に変換
replacement = r"await \1(\2) if __import__('asyncio').iscoroutinefunction(\1) else \1(\2)"
content = re.sub(
    r"background_tasks\.add_task\(\s*([a-zA-Z0-9_]+)\s*,\s*(.*?)\)",
    replacement,
    content
)

with open(target_file, "w", encoding="utf-8") as f:
    f.write(content)

print(f"✅ [成功] {target_file} の書き換えが完了しました！")

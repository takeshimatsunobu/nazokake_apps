import os
import re

PROJECT_DIR = r"C:\Users\takes\nazokake-evaluator"
EXCLUDE_DIRS = ['.git', '.venv_ai', '__pycache__', 'node_modules', 'build', 'models', 'llama.cpp']

print("==========================================")
print("🔍 過去のFirestoreコレクション名の探索")
print("==========================================")
# .collection('〇〇') や .collection("〇〇") のパターンを抽出
collection_pattern = re.compile(r'\.collection\([\'"]([^\'"]+)[\'"]\)')

for root, dirs, files in os.walk(PROJECT_DIR):
    # 除外ディレクトリをスキップ
    dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
    for file in files:
        if file.endswith('.py') or file.endswith('.js'):
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    matches = collection_pattern.findall(content)
                    if matches:
                        # 重複を排除して出力
                        unique_collections = set(matches)
                        print(f"📁 ファイル: {filepath.replace(PROJECT_DIR, '')}")
                        print(f"   => 検出されたコレクション: {unique_collections}\n")
            except Exception:
                pass

print("==========================================")
print("📝 プロンプト定義・システム設定ファイルの探索")
print("==========================================")
prompt_keywords = ['prompt', 'instruction', 'system_message', 'なぞかけを作成']

for root, dirs, files in os.walk(PROJECT_DIR):
    dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
    for file in files:
        if file.endswith('.py') or file.endswith('.json') or file.endswith('.txt'):
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for i, line in enumerate(f):
                        if any(k in line.lower() for k in prompt_keywords):
                            print(f"📄 {filepath.replace(PROJECT_DIR, '')} (行 {i+1}):")
                            print(f"   => {line.strip()[:100]}...\n")
            except Exception:
                pass
print("✅ 探索完了！")

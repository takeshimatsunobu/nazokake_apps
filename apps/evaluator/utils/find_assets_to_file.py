import os
import re

PROJECT_DIR = r"C:\Users\takes\nazokake-evaluator"
# 余計なログフォルダ（_ai_context）などを検索対象から除外
EXCLUDE_DIRS = ['.git', '.venv_ai', '__pycache__', 'node_modules', 'build', 'models', 'llama.cpp', '_ai_context', '.vscode']
OUTPUT_FILE = os.path.join(PROJECT_DIR, "search_results.txt")

with open(OUTPUT_FILE, 'w', encoding='utf-8') as out_f:
    out_f.write("==========================================\n")
    out_f.write("🔍 過去のFirestoreコレクション名の探索\n")
    out_f.write("==========================================\n")
    collection_pattern = re.compile(r'\.collection\([\'"]([^\'"]+)[\'"]\)')

    for root, dirs, files in os.walk(PROJECT_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for file in files:
            if file.endswith('.py') or file.endswith('.js'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                        matches = collection_pattern.findall(content)
                        if matches:
                            unique_collections = set(matches)
                            out_f.write(f"📁 ファイル: {filepath.replace(PROJECT_DIR, '')}\n")
                            out_f.write(f"   => 検出されたコレクション: {unique_collections}\n\n")
                except Exception:
                    pass

    out_f.write("==========================================\n")
    out_f.write("📝 プロンプト定義・システム設定ファイルの探索\n")
    out_f.write("==========================================\n")
    prompt_keywords = ['prompt', 'instruction', 'system_message', 'なぞかけ']

    for root, dirs, files in os.walk(PROJECT_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for file in files:
            if file.endswith('.py') or file.endswith('.json') or file.endswith('.txt'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        for i, line in enumerate(f):
                            if any(k in line.lower() for k in prompt_keywords):
                                out_f.write(f"📄 {filepath.replace(PROJECT_DIR, '')} (行 {i+1}):\n")
                                out_f.write(f"   => {line.strip()[:100]}...\n\n")
                except Exception:
                    pass
    out_f.write("✅ 探索完了！\n")

print(f"✅ 結果を {OUTPUT_FILE} に保存しました！VS Codeで開いて確認してください。")

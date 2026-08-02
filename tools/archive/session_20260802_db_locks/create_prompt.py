import os
os.makedirs('tools/instructions', exist_ok=True)
with open('tools/instructions/343_fix_e402_ollama.txt', 'w', encoding='utf-8') as f:
    f.write('''【ミッション: E402インポート臦序エラーの修正】
packages/shared_core/nazokake_core/database.py において、Ruff� E402 Module level import not at top of file エラーが睺生しています。
fileの中腹に挿入された from opentelemetry import metrics を、fileの先頭(他のmoduleレベルのインポート文が集まっている箇所)へ移動してください。
修正後、Ruffのチェック（uv run ruff check packages/shared_core/nazokake_core/database.py）を通過することを確認し、変更をコミットしてください《
commit message: fix(db): fix import order for opentelemetry''')

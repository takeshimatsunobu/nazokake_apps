import os

file_path = 'backend/main.py'
if not os.path.exists(file_path):
    print("⚠️ backend/main.py が見つかりません。")
    exit()

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 置換前のコード（通常のGeminiを呼び出している部分）
old_code = "model = genai.GenerativeModel('gemini-3.0-flash')"

# 置換後のコード（TUNED_MODEL_NAME があればそれを使い、無ければ通常版を使う）
new_code = '''# 💡 Takeshi専用チューニングモデルの読み込み設定
        model_name = os.environ.get("TUNED_MODEL_NAME", "gemini-3.0-flash")
        model = genai.GenerativeModel(model_name)'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("✅ 成功: main.py にカスタムモデルの受け入れ口を作成しました！")
else:
    print("⚠️ 既に修正されているか、対象のコードが見つかりませんでした。")

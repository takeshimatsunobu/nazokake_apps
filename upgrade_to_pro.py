import re

file_path = 'backend/main.py'
try:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 💡 一般的に使われている 'gemini-1.5-flash' や 'gemini-flash' を 'gemini-1.5-pro' に置換します
    # ※もしすでに別の名前で定義されている場合も考慮した正規表現
    new_content = re.sub(
        r'[\'"]gemini-(1\.5-)?flash([^\'"]*)[\'"]', 
        '"gemini-1.5-pro"', 
        content
    )
    
    # 古い gemini-pro (1.0) を使っていた場合のケア
    new_content = re.sub(
        r'[\'"]gemini-pro[\'"]', 
        '"gemini-1.5-pro"', 
        new_content
    )

    if new_content != content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("✅ 成功: main.py のAIモデルを 'gemini-1.5-pro' にアップグレードしました！")
    else:
        print("⚠️ 変更なし: 既にProモデルになっているか、モデル名の指定箇所が見つかりませんでした。")
        print("   ※手動で main.py 内のモデル指定（例: 'gemini-1.5-flash'）を 'gemini-1.5-pro' に変更してください。")

except Exception as e:
    print(f"🚨 エラーが発生しました: {e}")

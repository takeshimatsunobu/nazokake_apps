import os
import re

filepath = 'apps/evaluator/frontend/public/research_data/tab-definition.html'

if not os.path.exists(filepath):
    print(f"❌ エラー: {filepath} が見つかりません。")
else:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 縦潰れ（横幅の極限収縮）の元凶となったクラスをピンポイントで削除
    content = re.sub(r'\bself-start\b', '', content)
    content = re.sub(r'\bitems-start\b', '', content)
    
    # 余分な連続スペースを掃除
    content = re.sub(r' +', ' ', content)
    content = re.sub(r' "', '"', content)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    print("✅ 成功: 縦潰れの原因（self-start）を排除しました！")
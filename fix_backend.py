import os
import re

def fix_backend():
    file_path = 'backend/main.py'
    if not os.path.exists(file_path):
        print("⚠️ backend/main.py が見つかりません。")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # エラーの原因となっている「余分な閉じ括弧と重複パラメータ」を特定
    bad_string = 'False}, "parent_id": req.parent_id})'
    good_string = 'False})'

    if bad_string in content:
        content = content.replace(bad_string, good_string)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("✅ 成功: main.py の構文エラー(SyntaxError)を完全に修復しました！")
    else:
        # 念のための正規表現フォールバック
        new_content = re.sub(r'False\},\s*"parent_id":[^}]+\}\)', 'False})', content)
        if new_content != content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print("✅ 成功: 正規表現で main.py の構文エラーを修復しました！")
        else:
            print("⚠️ エラー箇所が見つかりませんでした。すでに修正されている可能性があります。")

if __name__ == '__main__':
    fix_backend()

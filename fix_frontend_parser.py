import os

file_path = 'frontend/index.html'
if not os.path.exists(file_path):
    print("⚠️ frontend/index.html が見つかりません。")
    exit()

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 置換前のコード
old_code = '''        if(match && match.length === 4) {
            document.getElementById('input-a').value = match[1].trim();
            document.getElementById('input-b').value = match[2].trim();
            document.getElementById('input-c').value = match[3].trim();
        }'''

# 置換後のコード（正規表現で先頭・末尾の「、」「「」「『」などを徹底的に削ぎ落とす）
new_code = '''        if(match && match.length === 4) {
            // 💡 AIの気まぐれな記号（、や「）をフォーム挿入前に完全に削ぎ落とす最強のサニタイズ！
            document.getElementById('input-a').value = match[1].replace(/^[、「『\s]+|[」』\s]+$/g, '');
            document.getElementById('input-b').value = match[2].replace(/^[、「『\s]+|[」』\s]+$/g, '');
            document.getElementById('input-c').value = match[3].replace(/^[、「『\s]+|[」』\s]+$/g, '');
        }'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("✅ 成功: frontend/index.html の表示要領（クリーニング機能）を修正しました！")
else:
    print("⚠️ 既に修正されているか、対象のコードが見つかりませんでした。")

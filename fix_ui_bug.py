import os

def fix_ui_bug():
    file_path = 'frontend/index.html'
    if not os.path.exists(file_path):
        print(f"⚠️ {file_path} が見つかりません。")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 安全に関数部分だけを置換するためのインデックス検索
    start_idx = content.find('function editNazokake(fullText, docId) {')
    if start_idx == -1:
        print("⚠️ editNazokake関数が見つかりませんでした。")
        return

    # 次の関数またはスクリプト終了タグを探す
    end_idx_1 = content.find('function ', start_idx + 10)
    end_idx_2 = content.find('</script>', start_idx + 10)
    
    if end_idx_1 != -1 and end_idx_2 != -1:
        end_idx = min(end_idx_1, end_idx_2)
    elif end_idx_1 != -1:
        end_idx = end_idx_1
    else:
        end_idx = end_idx_2

    new_func = '''function editNazokake(fullText, docId) {
        // 💡 1. まず前回の入力データを確実にクリア！（UI残存バグの修正）
        document.getElementById('input-a').value = '';
        document.getElementById('input-b').value = '';
        document.getElementById('input-c').value = '';
        window.currentEditingParentId = docId; // 血統をセット
        
        document.getElementById('editing-badge').style.display = 'block';
        document.getElementById('main-submit-btn').innerText = "整えました！ (AI作品を添削して道場破り)";

        // 💡 2. より強力で寛容なパーサー
        const match = fullText.match(/(?:「|『)?([^」』]+?)(?:」|』)?\s*とかけて.*?(?:「|『)?([^」』]+?)(?:」|』)?\s*と解く。.*?その心は[、\s]*(.*)$/is);

        if(match && match.length === 4) {
            document.getElementById('input-a').value = match[1].trim();
            document.getElementById('input-b').value = match[2].trim();
            document.getElementById('input-c').value = match[3].trim();
        } else {
            // 💡 3. パース失敗時も無視せず、フルテキストをCに入れてユーザーに委ねる！
            alert("AIの表現が特殊なため、自動で分解できませんでした。テキストボックス内で手動で整えてください！");
            document.getElementById('input-c').value = fullText;
        }

        window.scrollTo({ top: 0, behavior: 'smooth' });
        const postArea = document.getElementById('post-area');
        postArea.classList.add('highlight');
        setTimeout(() => { postArea.classList.remove('highlight'); }, 1500);
    }
    '''

    # 文字列の結合で安全に置換
    new_content = content[:start_idx] + new_func + content[end_idx:]

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
        print("✅ 成功: frontend/index.html の UIバグを完全に修正しました！")

if __name__ == '__main__':
    fix_ui_bug()

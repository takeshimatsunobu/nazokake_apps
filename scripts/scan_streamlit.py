from pathlib import Path

print("🤖 プロジェクト内のStreamlitファイルをスキャンしています...")
st_files = []
for p in Path('.').rglob('*.py'):
    # 環境依存フォルダやゴミ箱は厳格に除外
    if any(x in p.parts for x in ['.venv', '.venv_ai', 'node_modules', '_archive_trash']):
        continue
    try:
        content = p.read_text(encoding='utf-8')
        if 'import streamlit' in content:
            st_files.append(p)
    except:
        pass

if not st_files:
    print("\n⚠️ StreamlitのPythonファイルが見つかりません。完全にゼロから『新規作成』するフェーズです。")
else:
    for f in st_files:
        print(f"\n{'='*50}\n📄 発見: {f}\n{'='*50}")
        # 先頭30行（インポートや初期化ロジック）を抽出
        lines = f.read_text(encoding='utf-8').split('\n')[:30]
        print('\n'.join(lines))

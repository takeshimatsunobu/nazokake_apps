import os
from pathlib import Path
from datetime import datetime

def dump_project_status():
    root_dir = Path(os.getcwd())
    print(f"🔍 プロジェクトステータスをスキャン中: {root_dir.name}")
    
    target_exts = {'.py', '.json', '.html', '.js', '.yaml'}
    exclude_dirs = {'.venv', '.venv_ai', '__pycache__', '.git', 'node_modules', '.vscode'}
    
    file_list = []
    for path in root_dir.rglob('*'):
        if path.is_file() and path.suffix in target_exts:
            if not any(part in exclude_dirs for part in path.parts):
                stat = path.stat()
                mod_time = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                file_list.append(f"{path.relative_to(root_dir)} (Last Modified: {mod_time})")
    
    print("\n📁 【主要ファイル構成と最終更新日時】")
    for f in sorted(file_list):
        print(f"  - {f}")
        
    print("\n✅ ダンプ完了。この出力結果をGeminiに共有してください。")

if __name__ == "__main__":
    try:
        dump_project_status()
    except Exception as e:
        print(f"❌ エラー発生（位置特定: dump_project_status）: {e}")

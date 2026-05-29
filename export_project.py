import os
import math
from pathlib import Path

def get_target_dir():
    # 実行しているスクリプトと同じ場所にある "_ai_context" フォルダを指定
    root_dir = Path(__file__).parent.absolute()
    target_dir = root_dir / "_ai_context"
    return str(target_dir)

def generate_tree(dir_path, exclude_dirs, prefix=""):
    tree_str = ""
    try:
        entries = sorted(os.listdir(dir_path))
    except PermissionError:
        return ""
    
    entries = [e for e in entries if e not in exclude_dirs]
    for i, entry in enumerate(entries):
        path = os.path.join(dir_path, entry)
        is_last = (i == len(entries) - 1)
        connector = "└── " if is_last else "├── "
        tree_str += f"{prefix}{connector}{entry}\n"
        if os.path.isdir(path):
            extension = "    " if is_last else "│   "
            tree_str += generate_tree(path, exclude_dirs, prefix + extension)
    return tree_str

def export_context():
    root_dir = Path(__file__).parent.absolute()
    
    # 💡 スキャン対象とするファイルの拡張子
    target_exts = {'.py', '.json', '.md', '.txt', '.yaml', '.html', '.css', '.js'}
    
    # 💡 スキャンを除外するフォルダ（ここに書かれたフォルダはAIに送られません）
    exclude_dirs = {
        '.venv', '__pycache__', '.git', 'node_modules', 
        '.agents', '.vscode', 'data', '_ai_context',
        '_archive_tests', 'admin_scripts', 'backend-worker'
    }
    
    target_dir = get_target_dir()
    os.makedirs(target_dir, exist_ok=True)

    print(f"[{root_dir.name}] プロジェクトの構成をスキャン中...")
    
    all_lines = []

    # ==========================================
    # 1. ディレクトリツリーの生成と配列への追加
    # ==========================================
    all_lines.append("="*60)
    all_lines.append("📁 PROJECT DIRECTORY TREE")
    all_lines.append("="*60)
    # ツリーのテキストを改行ごとに分割して配列に追加
    all_lines.extend(generate_tree(str(root_dir), exclude_dirs).splitlines())
    all_lines.append("\n\n")
    
    # ==========================================
    # 2. ソースコードの収集
    # ==========================================
    print("ソースコードをスキャン中...")
    for path in root_dir.rglob('*'):
        if path.is_file() and path.suffix in target_exts:
            if not any(part in exclude_dirs for part in path.parts):
                # エクスポートスクリプト自身は出力から除外
                if path.name in ["export_project.py", os.path.basename(__file__)]:
                    continue
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        all_lines.append(f"\n\n{'='*60}")
                        all_lines.append(f"📄 File: {path.relative_to(root_dir)}")
                        all_lines.append(f"{'='*60}\n")
                        all_lines.extend(content.splitlines())
                except Exception:
                    pass

    if not all_lines:
        print("出力対象のコードが見つかりませんでした。")
        return

    # ==========================================
    # 3. ファイル構造 ＋ ソースコードの分割と保存
    # ==========================================
    # 💡 AIの読み込みエラーを防ぐための分割数（1にすれば1つのファイルにまとまります）
    split_count = 8 
    total_lines = len(all_lines)
    chunk_size = math.ceil(total_lines / split_count)
    
    print(f"全 {total_lines} 行のデータ（ファイル構成図 ＋ コード）を {split_count} 分割して出力します。\n")
    
    for i in range(split_count):
        start_idx = i * chunk_size
        end_idx = start_idx + chunk_size
        chunk_lines = all_lines[start_idx:end_idx]
        
        if not chunk_lines:
            continue
            
        out_file = os.path.join(target_dir, f"source_code_part_{i+1}.txt")
        with open(out_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(chunk_lines))
            
        print(f"✅ コード出力完了 ({i+1}/{split_count}): {out_file}")

if __name__ == "__main__":
    export_context()
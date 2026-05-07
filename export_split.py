import os
import math
from pathlib import Path

def get_downloads_dir():
    """OSごとのDownloadsディレクトリを自動取得（Windows対応）"""
    return str(Path.home() / "Downloads")

def export_context():
    # プロジェクトのルートディレクトリを取得
    root_dir = Path(__file__).parent.absolute()
    
    # 取得対象の拡張子と、除外するディレクトリ（仮想環境や不要なキャッシュ）
    target_exts = ['.py', '.json', '.md', '.txt']
    exclude_dirs = ['.venv', '__pycache__', '.git', 'node_modules', 'frontend-ui/.venv']
    
    all_lines = []
    
    print(f"[{root_dir.name}] プロジェクト内のファイルをスキャン中...")
    
    # ファイルの読み込みと結合
    for path in root_dir.rglob('*'):
        if path.is_file() and path.suffix in target_exts:
            # 除外ディレクトリが含まれていないかチェック
            if not any(excluded in path.parts for excluded in exclude_dirs):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        all_lines.append(f"\n\n{'='*60}")
                        all_lines.append(f"File: {path.relative_to(root_dir)}")
                        all_lines.append(f"{'='*60}\n")
                        all_lines.extend(content.splitlines())
                except Exception as e:
                    print(f"スキップしました (読み込みエラー): {path.name}")

    if not all_lines:
        print("出力対象のテキストが見つかりませんでした。")
        return

    # コードの途中で文字が切れないよう、行単位で4分割する
    downloads_dir = get_downloads_dir()
    os.makedirs(downloads_dir, exist_ok=True)
    
    total_lines = len(all_lines)
    chunk_size = math.ceil(total_lines / 4)
    
    print(f"全 {total_lines} 行のコードを4分割して {downloads_dir} へ出力します。\n")
    
    for i in range(4):
        start_idx = i * chunk_size
        end_idx = start_idx + chunk_size
        chunk_lines = all_lines[start_idx:end_idx]
        
        # 書き込み
        out_file = os.path.join(downloads_dir, f"nazokake_context_part_{i+1}.txt")
        with open(out_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(chunk_lines))
            
        print(f"✅ 出力完了 ({i+1}/4): {out_file}")

if __name__ == "__main__":
    export_context()
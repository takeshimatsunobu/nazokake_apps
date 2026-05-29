import os
from pathlib import Path

def export_all_clean():
    root_dir = Path(__file__).parent.absolute()
    target_dir = root_dir / "_ai_context"
    os.makedirs(target_dir, exist_ok=True)
    
    print(f"[{root_dir.name}] 🚀 独自コードをスキャン中（分割なし・インフラ除外）...")

    all_lines = []
    target_exts = {'.py', '.json', '.md', '.txt', '.yaml', '.html', '.css', '.js'}
    # 外部ライブラリやデータ、AIコンテキスト自体は除外して肥大化を防ぐ
    exclude_dirs = {'.venv', '__pycache__', '.git', 'node_modules', '.vscode', 'data', '_ai_context', 'nazokake_context_files'}

    for path in root_dir.rglob('*'):
        if path.is_file() and path.suffix in target_exts:
            if not any(part in exclude_dirs for part in path.parts):
                if path.name in ["export_clean.py", "export_project.py"]:
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
        print("出力対象が見つかりませんでした。")
        return

    out_file = target_dir / "source_code_complete_clean.txt"
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(all_lines))
    print(f"✅ クリーンコード出力完了: {out_file} (合計 {len(all_lines)} 行)")

if __name__ == '__main__':
    export_all_clean()

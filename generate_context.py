# generate_context.py
# 他AIへの引き継ぎ用コンテキストダンプ生成スクリプト。
# 対象拡張子のソースのみを、(1) ディレクトリツリー → (2) 各ファイルのパス＋中身 の順で
# UTF-8 の project_context.txt に書き出す。venv 等のノイズは完全除外する。

import os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(PROJECT_DIR, "project_context.txt")

# 除外ディレクトリ（名前一致でツリーから枝刈り）
EXCLUDE_DIRS = {
    ".venv_ai", "node_modules", ".git", "__pycache__",
    ".pytest_cache", ".firebase",
}
# 除外する相対パス（削除済みディレクトリ等をパス単位で枝刈り）
EXCLUDE_RELPATHS = {os.path.join("frontend", "public", "js")}

# 対象拡張子
TARGET_EXTS = {".py", ".js", ".html", ".css", ".md"}


def collect_files():
    """対象ファイルの相対パス（posix表記）を昇順で返す。"""
    collected = []
    for root, dirs, files in os.walk(PROJECT_DIR):
        rel_root = os.path.relpath(root, PROJECT_DIR)
        # 名前一致での枝刈り
        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDE_DIRS
            and os.path.normpath(os.path.join(rel_root, d)) not in EXCLUDE_RELPATHS
        ]
        for f in files:
            if os.path.splitext(f)[1].lower() in TARGET_EXTS:
                rel = os.path.normpath(os.path.join(rel_root, f))
                collected.append(rel.replace(os.sep, "/"))
    return sorted(collected)


def render_tree(paths):
    """対象ファイルのパス一覧からディレクトリツリー文字列を組み立てる。"""
    tree = {}
    for p in paths:
        node = tree
        for part in p.split("/"):
            node = node.setdefault(part, {})

    lines = ["."]

    def walk(node, prefix=""):
        entries = sorted(node.keys(), key=lambda k: (not node[k], k))  # ディレクトリ→ファイル
        for i, name in enumerate(entries):
            last = (i == len(entries) - 1)
            connector = "└── " if last else "├── "
            is_dir = bool(node[name])
            lines.append(f"{prefix}{connector}{name}{'/' if is_dir else ''}")
            if is_dir:
                walk(node[name], prefix + ("    " if last else "│   "))

    walk(tree)
    return "\n".join(lines)


def main():
    paths = collect_files()
    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        out.write("=" * 70 + "\n")
        out.write("なぞかけ道場 プロジェクト・コンテキスト（引き継ぎ用ダンプ）\n")
        out.write(f"対象拡張子: {', '.join(sorted(TARGET_EXTS))}\n")
        out.write(f"除外: {', '.join(sorted(EXCLUDE_DIRS))}, frontend/public/js\n")
        out.write(f"対象ファイル数: {len(paths)}\n")
        out.write("=" * 70 + "\n\n")

        out.write("【1. ディレクトリツリー（対象ファイルのみ）】\n")
        out.write(render_tree(paths) + "\n\n")

        out.write("【2. 各ファイルの中身】\n")
        for rel in paths:
            abs_path = os.path.join(PROJECT_DIR, rel.replace("/", os.sep))
            out.write("\n" + "=" * 70 + "\n")
            out.write(f"📄 {rel}\n")
            out.write("=" * 70 + "\n")
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    out.write(f.read())
            except Exception as e:
                out.write(f"[読み取り失敗: {e}]\n")
            out.write("\n")

    # .gitignore に project_context.txt を追記（未記載なら）
    gitignore = os.path.join(PROJECT_DIR, ".gitignore")
    entry = "project_context.txt"
    existing = []
    if os.path.exists(gitignore):
        with open(gitignore, "r", encoding="utf-8") as f:
            existing = [ln.strip() for ln in f]
    if entry not in existing:
        with open(gitignore, "a", encoding="utf-8") as f:
            f.write(("\n" if existing and existing[-1] != "" else "") + entry + "\n")
        print(f"✅ .gitignore に '{entry}' を追記しました。")
    else:
        print(f"ℹ️ .gitignore には既に '{entry}' が記載済みです。")

    size = os.path.getsize(OUTPUT_FILE)
    print(f"✅ {OUTPUT_FILE} を生成（{len(paths)} ファイル, {size:,} bytes / {size/1024:.1f} KB）")


if __name__ == "__main__":
    main()

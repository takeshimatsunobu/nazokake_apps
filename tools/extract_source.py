"""
tools/extract_source.py
=========================
apps/, packages/, tools/ 配下の全ソースコードを、AIのコンテキスト入力用に
単一のテキストファイル(リポジトリルートの all_source_code.txt)へダンプする。

環境・生成物ディレクトリ(.venv系, __pycache__, node_modules, .git等)や
バイナリ・ログ系拡張子(.db, .pyc, .png等)は完全にスキップし、ノイズの少ない
高signalなソースダンプにする。

【セキュリティ】serviceAccountKey.json / .env 等の秘密情報ファイルは、指示の
除外リストには無いが、平文の認証情報を単一の巨大テキストファイルへ複製する
リスクを避けるため、拡張子・ディレクトリの除外とは別枠で明示的に除外する。
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = ["apps", "packages", "tools"]
OUTPUT_PATH = REPO_ROOT / "all_source_code.txt"

# 環境・生成物ディレクトリ(ディレクトリ名の完全一致で、深さを問わず除外)。
EXCLUDED_DIR_NAMES = {
    ".venv", ".venv_ai", ".venv_train", ".venv_aider",
    "__pycache__", "node_modules", ".git",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", ".benchmarks",
    ".firebase", "chroma_db", "unsloth_compiled_cache", "llama-bin",
    ".aider.tags.cache.v4",
    # 過去の「全文コンテキスト抽出」の生成物置き場。ソースコードではなく、
    # secretを含む旧ダンプが混入していた実例(apps/evaluator/export_context_final/
    # context_part_01.md に serviceAccountKey.json の内容がそのまま含まれていた)が
    # あるため、除外する。
    "export_context_final", "_ai_context",
}

# バイナリ・ログ・アーカイブ等、コンテキストとして不要な拡張子。
EXCLUDED_EXTENSIONS = {
    ".db", ".pyc", ".pyo", ".log", ".tgz", ".whl", ".lock", ".png",
    ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".bmp",
    ".zip", ".tar", ".gz", ".7z", ".pdf",
    ".exe", ".dll", ".so", ".bin", ".pt", ".pth", ".safetensors", ".gguf",
    ".ttf", ".woff", ".woff2",
}

# ディレクトリ名の末尾一致で除外するパターン(例: "nazokake_core.egg-info")。
EXCLUDED_DIR_SUFFIXES = (".egg-info",)

# 秘密情報ファイル(拡張子/ディレクトリの除外とは別枠で、ファイル名で明示的に除外)。
# .aider.chat.history.md / .aider.input.history はソースコードではなく単なる
# AIツールとの対話ログだが、貼り付けられた秘密情報をそのまま記録してしまう実例が
# あったため、ここでも明示的に除外する(exportディレクトリの除外と合わせた多層防御)。
EXCLUDED_FILENAMES = {
    "serviceAccountKey.json",
    ".env",
    ".aider.chat.history.md",
    ".aider.input.history",
}
EXCLUDED_FILENAME_PREFIXES = (".env.",)

# 1ファイルあたりの最大サイズ(バイト)。想定外に巨大なデータファイル等が拡張子
# フィルタを素通りした場合の安全弁(超過時はスキップし標準出力に理由を記録する)。
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024

HEADER_LINE = "=" * 20


def _is_excluded_dir(dir_name: str) -> bool:
    if dir_name in EXCLUDED_DIR_NAMES:
        return True
    return dir_name.endswith(EXCLUDED_DIR_SUFFIXES)


def _is_excluded_file(path: Path) -> bool:
    if path.name in EXCLUDED_FILENAMES:
        return True
    if path.name.startswith(EXCLUDED_FILENAME_PREFIXES):
        return True
    return path.suffix.lower() in EXCLUDED_EXTENSIONS


def iter_source_files():
    """TARGET_DIRS配下を再帰的に走査し、除外対象を除いたファイルパスをyieldする。"""
    for target in TARGET_DIRS:
        target_dir = REPO_ROOT / target
        if not target_dir.is_dir():
            continue
        for path in sorted(target_dir.rglob("*")):
            if not path.is_file():
                continue
            if any(_is_excluded_dir(part) for part in path.relative_to(REPO_ROOT).parts[:-1]):
                continue
            if _is_excluded_file(path):
                continue
            yield path


def extract_all_source(output_path: Path = OUTPUT_PATH) -> tuple[int, int]:
    """ソースコードを1ファイルへダンプする。戻り値は (書き込んだファイル数, スキップしたファイル数)。"""
    written = 0
    skipped = 0
    with open(output_path, "w", encoding="utf-8", errors="replace") as out:
        for path in iter_source_files():
            try:
                size = path.stat().st_size
            except OSError as e:
                print(f"⚠️ スキップ(stat失敗): {path} ({e})")
                skipped += 1
                continue

            if size > MAX_FILE_SIZE_BYTES:
                print(f"⚠️ スキップ(サイズ超過 {size:,} bytes): {path}")
                skipped += 1
                continue

            rel_path = path.relative_to(REPO_ROOT).as_posix()
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                print(f"⚠️ スキップ(読み込み失敗): {rel_path} ({e})")
                skipped += 1
                continue

            out.write(f"{HEADER_LINE}\n")
            out.write(f"File: {rel_path}\n")
            out.write(f"{HEADER_LINE}\n")
            out.write(content)
            out.write("\n\n")
            written += 1

    return written, skipped


def main() -> None:
    written, skipped = extract_all_source()
    output_size = OUTPUT_PATH.stat().st_size
    print(
        f"✅ {OUTPUT_PATH.relative_to(REPO_ROOT)} を生成しました "
        f"(書き込み: {written}件, スキップ: {skipped}件, サイズ: {output_size:,} bytes)"
    )


if __name__ == "__main__":
    main()

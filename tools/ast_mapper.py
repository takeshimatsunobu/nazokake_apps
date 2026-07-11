"""
tools/ast_mapper.py
====================
Tool-Augmented Agent 用: シンボル名(関数/クラス)からその定義元ソースをASTで検索するツール。
"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_DIR_NAMES = {
    ".git", "__pycache__", ".mypy_cache", "node_modules",
    "unsloth_compiled_cache", "audit_reports",
}


def _is_excluded(py_file: Path) -> bool:
    for part in py_file.parts:
        if part in EXCLUDE_DIR_NAMES:
            return True
        if part.startswith(".venv") or "venv" in part:
            return True
    return False


def _display_path(py_file: Path) -> str:
    try:
        return str(py_file.relative_to(REPO_ROOT))
    except ValueError:
        return str(py_file)


def get_symbol_definition(target_dirs: list[Path], symbol_name: str) -> str:
    """target_dirs配下の.pyファイルをASTで走査し、symbol_nameに完全一致する
    関数(FunctionDef/AsyncFunctionDef)またはクラス(ClassDef)の定義元ソースを返す。

    文法エラーのあるファイルはスキップして走査を継続する(BOM付きファイルは
    encoding="utf-8-sig"で自動的に読める)。同名シンボルが複数見つかった場合は
    全結果を結合して返す。1件も見つからなければError文字列を返す。
    """
    results = []

    for target_dir in target_dirs:
        target_dir = Path(target_dir)
        if not target_dir.exists():
            continue
        for py_file in sorted(target_dir.rglob("*.py")):
            if _is_excluded(py_file):
                continue
            try:
                source = py_file.read_text(encoding="utf-8-sig")
                tree = ast.parse(source)
            except Exception:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if node.name != symbol_name:
                    continue
                segment = ast.get_source_segment(source, node)
                if segment is None:
                    continue
                end_lineno = getattr(node, "end_lineno", node.lineno)
                results.append(
                    f"[発見] {_display_path(py_file)} L{node.lineno}-L{end_lineno}\n{segment}"
                )

    if not results:
        return f"Error: シンボル '{symbol_name}' は見つかりませんでした。"

    return "\n\n".join(results)

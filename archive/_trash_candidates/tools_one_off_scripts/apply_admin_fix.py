import ast
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def apply_ast_driven_patch():
    file_path = Path("apps/evaluator/backend/api/routers/admin.py")
    if not file_path.exists():
        logger.error(f"{file_path} が見つかりません。")
        return False

    lines = file_path.read_text(encoding="utf-8").splitlines()
    tree = ast.parse("\n".join(lines))

    target_lineno = None
    indent_col = None

    # ASTツリーを探索し、置換対象となる代入文を決定的に特定する
    # SSoT原則: 正規表現やハードコードされた行番号は使用しない
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'updated':
                    if isinstance(node.value, ast.Await) and isinstance(node.value.value, ast.Call):
                        func = node.value.value.func
                        if getattr(func, 'id', '') == 'async_get_item':
                            target_lineno = node.lineno
                            indent_col = node.col_offset
                            break

    if target_lineno is None:
        logger.error("ASTパースエラー: ターゲットとなる async_get_item の呼び出しノードが見つかりません。")
        return False

    indent = " " * indent_col
    # Fail-Closed: Noneの場合は握り潰さず、直ちに例外(404)を送出する
    # この処理により、以降のコードで updated が確実に None でないこと(Type Narrowing)が保証されPyrightを通過する
    fail_closed_code = [
        f"{indent}if updated is None:",
        f"{indent}    from fastapi import HTTPException",
        f"{indent}    raise HTTPException(status_code=404, detail=\"Item not found or already deleted.\")"
    ]

    # コメントを維持したまま、ASTで特定した行の直後に安全に挿入
    new_lines = lines[:target_lineno] + fail_closed_code + lines[target_lineno:]
    file_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    logger.info("AST駆動による Fail-Closed パッチの適用に成功しました。")
    return True

if __name__ == "__main__":
    if not apply_ast_driven_patch():
        import sys
        sys.exit(1)

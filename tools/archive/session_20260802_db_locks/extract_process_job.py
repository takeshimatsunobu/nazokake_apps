import ast
from pathlib import Path

target = Path("workers/ondemand_elyza_worker.py")
source = target.read_text(encoding="utf-8")
tree = ast.parse(source)

for node in ast.walk(tree):
    if isinstance(node, ast.AsyncFunctionDef) and node.name == "_process_job":
        print("--- BEGIN _process_job ---")
        print(ast.unparse(node))
        print("--- END _process_job ---")
        break
import ast
import json
from pathlib import Path

def inspect_worker():
    target = Path("workers/ondemand_elyza_worker.py")
    if not target.exists():
        print(json.dumps({"error": "File not found"}))
        return
        
    with open(target, "r", encoding="utf-8") as f:
        source = f.read()
        
    tree = ast.parse(source)
    funcs = []
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            db_calls = []
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                    if "upsert" in child.func.id or "db" in child.func.id or "mark_" in child.func.id:
                        db_calls.append(child.func.id)
            funcs.append({"name": node.name, "db_calls": list(set(db_calls))})
            
    print(json.dumps({"file": str(target), "functions": funcs}, indent=2))

if __name__ == "__main__":
    inspect_worker()
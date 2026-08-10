import ast
import json
from pathlib import Path

def investigate_worker():
    targets = [
        Path('workers/ondemand_elyza_worker.py'),
        Path('apps/evaluator/backend/services/generation.py'),
        Path('apps/evaluator/backend/services/evaluation.py')
    ]
    
    results = {}
    for p in targets:
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding='utf-8'))
        funcs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                funcs.append(node.name)
        results[str(p)] = funcs
        
    print(json.dumps(results, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    investigate_worker()

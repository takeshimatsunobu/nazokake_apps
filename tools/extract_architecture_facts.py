import ast
import json
from pathlib import Path

def extract_system_facts():
    base_dir = Path(".").resolve()
    target_dirs = ["apps/evaluator/backend", "apps/batch_factory", "workers", "packages/shared_core"]
    
    facts = {}
    for d in target_dirs:
        dir_path = base_dir / d
        if not dir_path.exists():
            continue
            
        facts[d] = {}
        for p in dir_path.rglob("*.py"):
            if "pycache" in p.parts or p.name == "__init__.py":
                continue
            
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
                funcs = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
                classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
                facts[d][p.name] = {"classes": classes, "functions": funcs}
            except Exception as e:
                facts[d][p.name] = {"error": str(e)}


    output_path = base_dir / "run" / "architecture_facts.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ ファクト抽出完Һ: {output_path}")

if __name__ == "__main__":
    extract_system_facts()
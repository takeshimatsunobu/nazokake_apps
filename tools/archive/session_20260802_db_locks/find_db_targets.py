import ast,os
from pathlib import Path
def scan():
 targets=[]
 for r,d,f in os.walk("."):
  if any(x in r for x in [".venv","venv","node_modules","__pycache__",".git"]):continue
  for file in f:
   if file.endswith(".py"):
    p=Path(r)/file
    try:
     tree=ast.parse(p.read_text(encoding="utf-8"))
     for node in ast.walk(tree):
      if isinstance(node,ast.AsyncFunctionDef):
       has_tx=False
       for child in ast.walk(node):
        if isinstance(child,ast.AsyncWith):
         for item in child.items:
          if isinstance(item.context_expr,ast.Call) and getattr(item.context_expr.func,"attr","")=="begin":has_tx=True
       if has_tx:targets.append(f"{p}::{node.name}")
    except:pass
 print("=== DB Transaction Functions ===")
 for t in targets:print(t)
if __name__=="__main__":scan()
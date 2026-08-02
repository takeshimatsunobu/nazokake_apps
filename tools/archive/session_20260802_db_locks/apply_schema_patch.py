import libcst as cst
from pathlib import Path
import subprocess

target_file = Path("packages/shared_core/nazokake_core/schemas.py")

with open(target_file, "r", encoding="utf-8") as f:
    source = f.read()

module = cst.parse_module(source)

class AddCoTClass(cst.CSTTransformer):
    def __init__(self):
        self.exists = False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        if node.name.value == "NazokakeCoTOutput":
            self.exists = True
        return True

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        if self.exists:
            return updated_node
        new_class = cst.parse_statement('''
class NazokakeCoTOutput(BaseModel):
    reasoning_scratchpad: str
    ochi_c: str
    toki_b: str
    final_text: str
''')
        new_body = list(updated_node.body)
        new_body.append(new_class)
        return updated_node.with_changes(body=new_body)

transformer = AddCoTClass()
modified_module = module.visit(transformer)

if not transformer.exists:
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(modified_module.code)
    print("Success: NazokakeCoTOutput added.")
    subprocess.run(["git", "add", str(target_file)], check=True)
    subprocess.run(["git", "commit", "-m", "feat(schemas): add NazokakeCoTOutput for decoupled generation"], check=True)
    print("Success: Git commit completed.")
else:
    print("Warning: NazokakeCoTOutput already exists.")
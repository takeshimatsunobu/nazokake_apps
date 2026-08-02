import libcst as cst
import subprocess
TARGET_FILE = "packages/shared_core/nazokake_core/database.py"
class ImportMover(cst.CSTTransformer):
import_node = None
code
Code
def leave_ImportFrom(self, original_node, updated_node):
    if getattr(original_node.module, "value", "") == "opentelemetry":
        self.import_node = cst.SimpleStatementLine(body=[updated_node])
        return cst.RemoveFromParent()
    return updated_node

def leave_Module(self, original_node, updated_node):
    if not self.import_node:
        return updated_node

    insert_idx = 0
    for i, node in enumerate(updated_node.body):
        if isinstance(node, cst.SimpleStatementLine) and isinstance(node.body[0], (cst.Import, cst.ImportFrom)):
            insert_idx = i + 1

    new_body = list(updated_node.body)
    new_body.insert(insert_idx, self.import_node)
    return updated_node.with_changes(body=new_body)
def main():
with open(TARGET_FILE, "r", encoding="utf-8") as f:
tree = cst.parse_module(f.read())
code
Code
modified_tree = tree.visit(ImportMover())

with open(TARGET_FILE, "w", encoding="utf-8") as f:
    f.write(modified_tree.code)
    
print("Successfully moved opentelemetry import to the top.")
subprocess.run(["uv", "run", "ruff", "check", "--select", "I", "--fix", TARGET_FILE], check=False)
subprocess.run(["uv", "run", "ruff", "format", TARGET_FILE], check=False)
subprocess.run(["git", "add", TARGET_FILE], check=True)
subprocess.run(["git", "commit", "-m", "fix(db): fix import order for opentelemetry"], check=True)
print("Commit successful.")
main()

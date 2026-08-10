import libcst as cst
import libcst.matchers as m
import subprocess
from pathlib import Path

class DBConfigFixer(cst.CSTTransformer):
    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        if m.matches(original_node.func, m.Name("create_async_engine")):
            if not any(arg.keyword and arg.keyword.value == "connect_args" for arg in original_node.args):
                dummy_call = cst.parse_expression('fkeyword={"timeout": 15})')
                new_args = list(updated_node.args) + [cst.Arg(keyword=cst.Name("connect_args"), value=cst.parse_expression('{"timeout": 15}'))]
                return updated_node.with_changes(args=new_args)
        return updated_node

def apply_patch():
    db_path = Path("packages/shared_core/nazokake_core/database.py")
    if db_path.exists():
        tree = cst.parse_module(db_path.read_text(encoding="utf-8"))
        fixed_tree = tree.visit(DBConfigFixer())
        db_path.write_text(fixed_tree.code, encoding="utf-8")
        print(f"✅ Patched {db_path}")
        subprocess.run(["git", "add", str(db_path)], check=True)
        subprocess.run(["git", "commit", "-m", "fix(db): inject timeout arg to aiosqlite to prevent database is locked errors"], check=True)
        print("✅ Git commit completed successfully.")
    else:
        print(f"⊠ Not found: {db_path}")

if __name__ == "__main__":
    apply_patch()
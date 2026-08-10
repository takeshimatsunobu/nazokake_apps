import libcst as cst
import libcst.matchers as m
import subprocess
from pathlib import Path

class EnvConfigFixer(cst.CSTTransformer):
    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        new_body = []
        for stmt in updated_node.body:
            if m.matches(stmt, m.SimpleStatementLine(body=[m.Assign(targets=[m.AssignTarget(target=m.Name("env_file"))])])):
                base_dir_stmt = cst.parse_statement('BASE_DIR = Path(__file__).resolve().parents[3]')
                env_file_stmt = cst.parse_statement('env_file = BASE_DIR / ".env"')
                new_body.append(base_dir_stmt)
                new_body.append(env_file_stmt)
            else:
                new_body.append(stmt)
        return updated_node.with_changes(body=new_body)

class DBConfigFixer(cst.CSTTransformer):
    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        if m.matches(original_node.func, m.Name("create_async_engine")):
            if not any(arg.keyword and arg.keyword.value == "connect_args" for arg in original_node.args):
                dummy_call = cst.parse_expression('f(connect_args={"timeout": 15})')
                new_args = list(updated_node.args) + [dummy_call.args[0]]
                return updated_node.with_changes(args=new_args)
        return updated_node

def apply_patch():
    env_path = Path("packages/shared_core/nazokake_core/env_config.py")
    if env_path.exists():
        tree = cst.parse_module(env_path.read_text(encoding="utf-8"))
        fixed_tree = tree.visit(EnvConfigFixer())
        env_path.write_text(fixed_tree.code, encoding="utf-8")
        print(f"✅ Patched {env_path}")
    else:
        print(f"⊠ Not found: {env_path}")

    db_path = Path("packages/shared_core/nazokake_core/database.py")
    if db_path.exists():
        tree = cst.parse_module(db_path.read_text(encoding="utf-8"))
        fixed_tree = tree.visit(DBConfigFixer())
        db_path.write_text(fixed_tree.code, encoding="utf-8")
        print(f"✅ Patched {db_path}")
    else:
        print(f"⊠ Not found: {db_path}")

    subprocess.run(["git", "add", str(env_path), str(db_path)], check=True)
    subprocess.run(["git", "commit", "-m", "fix(infra): resolve .env path drift and inject SQLite timeout via LibCST"], check=True)
    print("✅ Git commit completed successfully.")

if __name__ == "__main__":
    apply_patch()

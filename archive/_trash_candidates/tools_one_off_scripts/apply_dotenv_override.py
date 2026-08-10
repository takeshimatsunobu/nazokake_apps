import libcst as cst
import libcst.matchers as m
import subprocess
from pathlib import Path

class OverrideTransformer(cst.CSTTransformer):
    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        if m.matches(original_node.func, m.Name("load_dotenv")):
            if any(arg.keyword and arg.keyword.value == "override" for arg in original_node.args):
                return updated_node
            dummy = cst.parse_expression("f(override=True)")
            new_arg = dummy.args[0]
            new_args = list(updated_node.args) + [new_arg]
            return updated_node.with_changes(args=new_args)
        return updated_node

def apply_patch():
    env_path = Path("packages/shared_core/nazokake_core/env_config.py")
    if env_path.exists():
        tree = cst.parse_module(env_path.read_text(encoding="utf-8"))
        fixed_tree = tree.visit(OverrideTransformer())
        env_path.write_text(fixed_tree.code, encoding="utf-8")
        print(f"✅ Patched {env_path}")
        subprocess.run(["git", "add", str(env_path)], check=True)
        subprocess.run(["git", "commit", "-m", "fix(infra): enforce dotenv override to prevent OS env var leakage"], check=True)
        print("✅ Git commit completed successfully.")
    else:
        print(f"⊠ Not found: {env_path}")

if __name__ == "__main__":
    apply_patch()
import libcst as cst
import subprocess

TARGET_FILE = "packages/shared_core/nazokake_core/database.py"

class RetryLoggingAdder(cst.CSTTransformer):
    def leave_ImportFrom(self, original_node, updated_node):
        if getattr(original_node.module, "value", "") == "tenacity":
            has_before_sleep = any(name.name.value == "before_sleep_log" for name in original_node.names)
            if not has_before_sleep:
                new_names = list(original_node.names) + [cst.ImportAlias(cst.Name("before_sleep_log"))]
                return updated_node.with_changes(names=new_names)
        return updated_node

    def leave_Call(self, original_node, updated_node):
        if isinstance(original_node.func, cst.Name) and original_node.func.value == "retry":
            has_before_sleep = any(arg.keyword and arg.keyword.value == "before_sleep" for arg in original_node.args)
            if not has_before_sleep:
                log_arg = cst.Arg(
                    keyword=cst.Name("before_sleep"),
                    value=cst.Call(
                        func=cst.Name("before_sleep_log"),
                        args=[
                            cst.Arg(value=cst.Name("logger")),
                            cst.Arg(value=cst.Attribute(value=cst.Name("logging"), attr=cst.Name("WARNING")))
                        ]
                    )
                )
                new_args = list(original_node.args) + [log_arg]
                return updated_node.with_changes(args=new_args)
        return updated_node

def main():
    with open(TARGET_FILE, "r", encoding="utf-8") as f:
        tree = cst.parse_module(f.read())
    
    modified_tree = tree.visit(RetryLoggingAdder())
    
    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        f.write(modified_tree.code)
        
    print("Successfully injected before_sleep_log into with_db_retry.")
    subprocess.run(["uv", "run", "ruff", "check", "--select", "I", "--fix", TARGET_FILE], check=False)
    subprocess.run(["uv", "run", "ruff", "format", TARGET_FILE], check=False)
    subprocess.run(["git", "add", TARGET_FILE, __file__], check=True)
    subprocess.run(["git", "commit", "-m", "feat(db): add observability logging to database retry mechanism"], check=True)
    print("Commit successful.")

if __name__ == "__main__":
    main()
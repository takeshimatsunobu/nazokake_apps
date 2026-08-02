import libcst as cst
import subprocess

TARGET_FILE = "packages/shared_core/nazokake_core/database.py"

class PragmaInjector(cst.CSTTransformer):
    def leave_SimpleStatementLine(self, original_node, updated_node):
        is_busy_timeout = False
        for stmt in original_node.body:
            if isinstance(stmt, cst.Expr) and isinstance(stmt.value, cst.Call):
                call = stmt.value
                if isinstance(call.func, cst.Attribute) and call.func.attr.value == "execute":
                    if len(call.args) > 0 and isinstance(call.args[0].value, cst.SimpleString):
                        if "busy_timeout" in call.args[0].value.value:
                            is_busy_timeout = True
        
        if is_busy_timeout:
            pragmas = [
                'cursor.execute("PRAGMA synchronous=NORMAL;")',
                'cursor.execute("PRAGMA mmap_size=30000000000;")',
                'cursor.execute("PRAGMA temp_store=MEMORY;")',
                'cursor.execute("PRAGMA cache_size=-64000;")'
            ]
            new_nodes = [updated_node]
            for p in pragmas:
                new_nodes.append(cst.parse_statement(p + "\n"))
            return cst.FlattenSentinel(new_nodes)
        
        return updated_node

def main():
    with open(TARGET_FILE, "r", encoding="utf-8") as f:
        source = f.read()
    
    if "synchronous=NORMAL" in source:
        print("PRAGMAs already injected.")
        return
    
    tree = cst.parse_module(source)
    modified_tree = tree.visit(PragmaInjector())
    
    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        f.write(modified_tree.code)
        
    print("Successfully injected SQLite PRAGMAs.")
    subprocess.run(["uv", "run", "ruff", "check", "--select", "I", "--fix", TARGET_FILE], check=False)
    subprocess.run(["uv", "run", "ruff", "format", TARGET_FILE], check=False)
    subprocess.run(["git", "add", TARGET_FILE], check=True)
    subprocess.run(["git", "commit", "-m", "perf(db): tune SQLite PRAGMA for high concurrency (Phase 1.5)"], check=True)
    print("Commit successful.")

if __name__ == "__main__":
    main()
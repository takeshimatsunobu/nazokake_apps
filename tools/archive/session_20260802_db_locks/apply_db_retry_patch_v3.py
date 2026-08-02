import libcst as cst
import subprocess

TARGET_FILE = "packages/shared_core/nazokake_core/database.py"

def main():
    print("Reverting file to HEAD...")
    subprocess.run(["git", "checkout", "HEAD", "--", TARGET_FILE], check=True)
    
    with open(TARGET_FILE, "r", encoding="utf-8") as f:
        source = f.read()
        
    tree = cst.parse_module(source)
    
    imports_code = (
        "from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type\n"
        "import sqlite3\n"
        "from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError\n"
    )
    imports_body = cst.parse_module(imports_code).body
    
    retry_code = (
        "\n\ndef with_db_retry():\n"
        "    return retry(\n"
        "        stop=stop_after_attempt(5),\n"
        "        wait=wait_exponential_jitter(initial=1, max=10, exp_base=2, jitter=1),\n"
        "        retry=retry_if_exception_type((sqlite3.OperationalError, SQLAlchemyOperationalError))\n"
        "    )\n"
    )
    retry_body = cst.parse_module(retry_code).body
    
    insert_idx = 0
    for i, node in enumerate(tree.body):
        if isinstance(node, cst.SimpleStatementLine):
            stmt = node.body[0]
            if isinstance(stmt, cst.Expr) and isinstance(stmt.value, (cst.SimpleString, cst.ConcatenatedString)):
                insert_idx = i + 1
                continue
            if isinstance(stmt, cst.ImportFrom) and getattr(stmt.module, "value", "") == "__future__":
                insert_idx = i + 1
                continue
        break
        
    new_body = list(tree.body[:insert_idx]) + list(imports_body) + list(tree.body[insert_idx:]) + list(retry_body)
    modified_tree = tree.with_changes(body=new_body)
    
    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        f.write(modified_tree.code)
        
    print("AST injection successful. Formatting and committing...")
    subprocess.run(["uv", "run", "ruff", "check", "--select", "I", "--fix", TARGET_FILE], check=False)
    subprocess.run(["uv", "run", "ruff", "format", TARGET_FILE], check=False)
    subprocess.run(["git", "add", TARGET_FILE], check=True)
    subprocess.run(["git", "commit", "-m", "fix(db): inject tenacity retry mechanism into database.py"], check=True)
    print("Commit successful.")

if __name__ == "__main__":
    main()
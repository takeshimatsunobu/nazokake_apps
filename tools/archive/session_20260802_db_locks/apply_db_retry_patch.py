import libcst as cst
import os
import subprocess

TARGET_FILE = "packages/shared_core/nazokake_core/database.py"

def main():
    if not os.path.exists(TARGET_FILE):
        print(f"Error: {TARGET_FILE} not found.")
        return

    with open(TARGET_FILE, "r", encoding="utf-8") as f:
        source = f.read()

    if "with_db_retry" in source:
        print("Retry mechanism already injected.")
        return

    tree = cst.parse_module(source)
    
    imports = cst.parse_module(
        "from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type\n"
        "import sqlite3\n"
        "from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError\n"
    ).body

    retry_func = cst.parse_module(        "\n\ndef with_db_retry():\n"
        "    return retry(\n"
        "        stop=stop_after_attempt(5),\n"
        "        wait=wait_exponential_jitter(initial=1, max=10, exp_base=2, jitter=1),\n"
        "        retry=retry_if_exception_type((sqlite3.OperationalError, SQLAlchemyOperationalError))\n"
        "    )\n"
    ).body

    new_body = list(imports) + list(tree.body) + list(retry_func)
    modified_tree = tree.with_changes(body=new_body)

    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        f.write(modified_tree.code)


    print(f"Successfully injected retry mechanism into {TARGET_FILE}")

    subprocess.run(["git", "add", TARGET_FILE, __file__], check=True)
    subprocess.run(["git", "commit", "-m", "fix(db): inject tenacity retry mechanism into database.py"], check=True)
    print("Committed changes.")

if __name__ == "__main__":
    main()
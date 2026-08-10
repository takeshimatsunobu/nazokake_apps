import ast
from pathlib import Path
db_path = Path("packages/shared_core/nazokake_core/database.py")
if db_path.exists():
    lines = db_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if "create_async_engine" in line or "connect_args" in line or "timeout" in line:
            print(f"L{i+1}: {line.strip()}")

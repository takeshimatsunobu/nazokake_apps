from pathlib import Path

path = Path("packages/shared_core/nazokake_core/env_config.py")
if path.exists():
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if ".env" in line or "dotenv" in line or "BASE_DIR" in line:
            print(f"L{i+1}: {line.strip()}")
else:
    print("env_config.py not found.")

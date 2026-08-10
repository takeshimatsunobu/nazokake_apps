from pathlib import Path
import sys

print("--- Scanning run/audit_reports for Errors ---")
target_dir = Path("run/audit_reports")
if not target_dir.exists():
    print(f"Directory not found: {target_dir}")
    sys.exit(0)

for p in target_dir.glob("*elyza*.*"):
    print(d"\nchecking: {p}")
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-30:]:
            print(line)
    except Exception as e:
        print(d"Could not read {p}: {e}")

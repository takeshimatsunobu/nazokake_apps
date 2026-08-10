import sqlite3
from pathlib import Path

print("--- database.py engine setup ---")
db_path = Path('packages/shared_core/nazokake_core/database.py')
# Parse lines instead of regex to avoid breakage
lines = db_path.read_text(encoding='utf-8').splitlines()
for l in lines:
    if 'create_async_engine' in l:
        print(l.strip())

print("\n--- SQLite JOURNAL_MODE ---")
try:
    conn = sqlite3.connect('nazokake_local.db')
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()
    print(f"Journal Mode: {mode[0]}")
    conn.close()
except Exception as e:
    print(e)

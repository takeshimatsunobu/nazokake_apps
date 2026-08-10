import subprocess
from pathlib import Path
p = Path('packages/shared_core/nazokake_core/database.py')
if p.exists():
    t = p.read_text(encoding='utf-8')
    if 'connect_args=' not in t:
        t = t.replace(
            'create_async_engine(_resolve_db_url(), future=True, poolclass=NullPool)',
            'create_async_engine(_resolve_db_url(), future=True, poolclass=NullPool, connect_args={"timeout": 15})'
        )
        p.write_text(t, encoding='utf-8')
        print("Patched database.py successfully.")
        subprocess.run(["git", "add", str(p)], check=True)
        subprocess.run(["git", "commit", "-m", "fix(db): inject timeout arg to aiosqlite to prevent database is locked errors"], check=True)
        print("Git commit completed successfully.")
    else:
        print("Already patched.")

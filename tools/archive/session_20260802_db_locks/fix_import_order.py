import os
os.system('uv run ruff check --select I,F404,E402 --fix packages/shared_core/nazokake_core/database.py')
os.system('git add packages/shared_core/nazokake_core/database.py tools/apply_db_retry_patch.py')
os.system('git commit -m "fix(db): inject tenacity retry mechanism"')

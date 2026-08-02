import subprocess
subprocess.run(["git", "reset"], check=True)
subprocess.run(["git", "add", "packages/shared_core/nazokake_core/database.py"], check=True)
subprocess.run(["git", "commit", "-m", "fix(db): inject tenacity retry mechanism into database.py"], check=True)
print("Commit successful.")
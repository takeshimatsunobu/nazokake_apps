import os
import subprocess

print("=== Tools Directory ===")
for f in os.listdir("tools"):
    if f.endswith(".py"):
        print(f)

print("\n === nazo_agent.py help ===")
try:
    subprocess.run(["uv", "run", "python", "tools/nazo_agent.py", "--help"])
except Exception as e:
    print(f"Error running nazo_agent.py: {e}")

import os, subprocess
os.chdir("packages/shared_core")
subprocess.run(["uv", "add", "opentelemetry-api", "opentelemetry-sdk"], check=True)
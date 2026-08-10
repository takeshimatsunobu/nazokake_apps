import sys
from pathlib import Path
sys.path.insert(0, str(Path('packages/shared_core').resolve()))
try:
    from nazokake_core import env_config
    print(f"📀 Resolved .env path: {env_config.env_file}")
    print(f"📀 File exists: {env_config.env_file.exists()}")
    if env_config.api_key:
        print(f"� GEMINI_API_KEY loaded. Length: {len(env_config.api_key)}")
    else:
        print("❌ GEMINI_API_KEY is not loaded.")
except Exception as e:
    print(f"❌ Exception: {e}")
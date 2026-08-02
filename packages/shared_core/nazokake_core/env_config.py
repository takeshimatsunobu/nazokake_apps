import os
from pathlib import Path
from dotenv import load_dotenv

def _load_env():
    # このファイル自身の場所から上に向かって絶対パスで .env を探す
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        env_file = parent / ".env"
        if env_file.exists():
            load_dotenv(dotenv_path=env_file)
            return
    # 見つからない場合のフォールバック
    load_dotenv()

# モジュール読み込み時に確実に実行
_load_env()

def get_gemini_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Critical Error: GEMINI_API_KEY is not set in the environment.")
    return api_key.strip()

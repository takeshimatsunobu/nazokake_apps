import os
import json
from dotenv import load_dotenv

# 💡 修正点1: 確実に `backend/.env` を読み込むように絶対パスを指定
current_dir = os.path.dirname(__file__)  # core/ フォルダ
backend_dir = os.path.dirname(current_dir) # backend/ フォルダ
env_path = os.path.join(backend_dir, '.env')
load_dotenv(dotenv_path=env_path)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 💡 修正点2: フォールバック（初期値）も正しいモデル名「gemini-3-flash-preview」に変更
EVALUATOR_MODEL_NAME = os.environ.get("EVALUATOR_MODEL_NAME", "gemini-3-flash-preview")

FIREBASE_CRED_PATH = "serviceAccountKey.json"

# prompt_config.json の読み込み
config_path = os.path.join(current_dir, "prompt_config.json")
try:
    with open(config_path, "r", encoding="utf-8") as f:
        PROMPT_CONFIG = json.load(f)
except Exception as e:
    print(f"🚨 prompt_config.json load error: {e}")
    PROMPT_CONFIG = {"system_instruction": "", "weights": {"default": 1.0}}

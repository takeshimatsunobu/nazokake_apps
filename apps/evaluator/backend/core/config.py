import os
import json
from dotenv import load_dotenv

from nazokake_core.env_config import get_gemini_api_key

# 現在のディレクトリ(core)と親ディレクトリ(backend)、プロジェクトルートを解決
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(backend_dir)

# 🌟 環境変数の唯一の情報源（SSoT）であるルートの .env をロード
env_path = os.path.join(project_root, ".env")
load_dotenv(dotenv_path=env_path)

# GEMINI_API_KEY自体の取得経路は nazokake_core.env_config へ一元化した
# (instructions/303)。ここでのload_dotenv()は本ファイルが引き続き読む
# 他の環境変数(EVALUATOR_MODEL_NAME等)のために維持する。
GEMINI_API_KEY = get_gemini_api_key()
EVALUATOR_MODEL_NAME = os.environ.get("EVALUATOR_MODEL_NAME", "gemini-3-flash-preview")

# Firebase認証ファイルパス
FIREBASE_CRED_PATH = "serviceAccountKey.json"

# prompt_config.json の読み込み
config_path = os.path.join(current_dir, "prompt_config.json")
try:
    with open(config_path, "r", encoding="utf-8") as f:
        PROMPT_CONFIG = json.load(f)
except Exception as e:
    print(f"🚨 prompt_config.json load error: {e}")
    PROMPT_CONFIG = {"system_instruction": "", "weights": {"default": 1.0}}

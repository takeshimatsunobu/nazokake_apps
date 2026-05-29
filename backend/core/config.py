import os
import json
from dotenv import load_dotenv

# 現在のファイルディレクトリを取得
current_dir = os.path.dirname(os.path.abspath(__file__))
# 親ディレクトリ（backend/）を取得
backend_dir = os.path.dirname(current_dir)

# .env ファイルのパスを構築し、環境変数をロード
env_path = os.path.join(backend_dir, '.env')
load_dotenv(dotenv_path=env_path)

# 環境変数からAPIキーとモデル名を読み込む
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
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
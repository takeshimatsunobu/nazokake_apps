# tools/test_api_key.py
import os
from nazokake_core.env_config import get_gemini_api_key

def main():
    print("🔍 APIキーのロードテストを開始します...")
    try:
        key = get_gemini_api_key()
        key_stripped = key.strip()
        
        print(f"✅ ロード成功")
        print(f"🔑 認識しているキー: {key_stripped[:5]} ******** {key_stripped[-4:]}")
        print(f"📏 文字数: {len(key_stripped)} (末尾スペース有無: {len(key) == len(key_stripped)})")
        
        # SSoTモジュールが本当にルートの.envを読んでいるか確認
        env_file = os.path.abspath(".env")
        print(f"📁 .envファイルの想定位置: {env_file} (存在: {os.path.exists(env_file)})")
        
    except Exception as e:
        print(f"❌ エラー: {e}")

if __name__ == "__main__":
    main()
import os
from google import genai

def list_available_models():
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("🚨 backend/.env からGEMINI_API_KEYが読み込めません。")
            return
            
        client = genai.Client(api_key=api_key)
        print("================ [ 利用可能な最新モデル一覧 ] ================")
        
        models = client.models.list()
        flash_models = []
        pro_models = []
        
        for model in models:
            if "gemini" in model.name:
                if "flash" in model.name:
                    flash_models.append(model.name)
                elif "pro" in model.name:
                    pro_models.append(model.name)
        
        print("\n⚡ Flash系 (生成用バックアップ候補):")
        for m in sorted(flash_models, reverse=True):
            print(f"  - {m}")
            
        print("\n🧠 Pro系 (評価用バックアップ候補):")
        for m in sorted(pro_models, reverse=True):
            print(f"  - {m}")
            
    except Exception as e:
        print(f"🚨 API通信エラー: {e}")

if __name__ == "__main__":
    from dotenv import load_dotenv
    # backendフォルダの.envを読み込む
    load_dotenv(dotenv_path="backend/.env")
    list_available_models()

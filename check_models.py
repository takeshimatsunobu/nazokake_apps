import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

def check_models():
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        print('🚨 GEMINI_API_KEYが設定されていません。')
        return

    client = genai.Client(api_key=api_key)
    
    print('📋 あなたのAPIキーで現在利用可能なモデル一覧:')
    print('-' * 50)
    
    try:
        models = client.models.list()
        for m in models:
            # "gemini" という名前が含まれるモデルだけを絞り込んで表示
            if "gemini" in m.name.lower():
                print(f"🟢 {m.name}")
    except Exception as e:
        print(f"🚨 通信エラー: {e}")
        
    print('-' * 50)

if __name__ == '__main__':
    check_models()

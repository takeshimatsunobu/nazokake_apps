import os
from google import genai

def main():
    # 1. APIキーの存在確認
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("エラー: 環境変数 'GEMINI_API_KEY' が設定されていません。")
        print("PowerShellで以下を実行してください:")
        print('$env:GEMINI_API_KEY="あなたのAPIキー"')
        return

    print("■ 利用可能なGeminiモデル一覧をフェッチしています（新SDK）...\n")
    
    try:
        # 2. 新しいSDKのクライアント初期化 (環境変数から自動的にキーを読み込みます)
        client = genai.Client()
        
        # 3. モデル一覧の取得
        models = client.models.list()
        
        for model in models:
            name = model.name
            # Gemini系のモデルのみを抽出してわかりやすく表示
            if "gemini" in name:
                if "gemini-3" in name:
                    print(f"⭐ 発見 (次世代モデル): {name}")
                elif "gemini-2.5" in name:
                    print(f"🟢 発見 (現行メイン): {name}")
                else:
                    print(f"  - {name}")
                    
    except Exception as e:
        print(f"API呼び出し中にエラーが発生しました: {e}")

if __name__ == "__main__":
    main()
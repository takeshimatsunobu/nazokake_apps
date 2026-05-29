import urllib.request
import json
import traceback

def check_ollama_status():
    print("\n================ [ Ollama ローカルサーバー稼働確認 ] ================")
    url = "http://localhost:11434/api/tags"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3.0) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                models = [model['name'] for model in data.get('models', [])]
                print("✅ Ollamaサーバー: 稼働中 (Port 11434)")
                print(f"📦 利用可能なローカルモデル: {', '.join(models) if models else 'モデルなし'}")
            else:
                print(f"⚠️ Ollamaサーバーは応答しましたが、ステータスが異常です: {response.status}")
    except urllib.error.URLError as e:
        print("🚨 Ollamaサーバーに接続できません。バックグラウンドでOllamaアプリが起動していない可能性があります。")
        print(f"   詳細: {e.reason}")
    except Exception as e:
        print("🚨 予期せぬエラーが発生しました:")
        traceback.print_exc()

if __name__ == "__main__":
    check_ollama_status()

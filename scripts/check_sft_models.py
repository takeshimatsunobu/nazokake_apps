import vertexai
from vertexai.tuning import sft

PROJECT_ID = "nazokakeapp-137e5"
# SFT機能が最も早く開放される us-central1 で確認します
REGION = "us-central1"

def check_supported_models():
    print(f"🔍 Vertex AI ({REGION}) でSFT可能なモデルを照会中...\n")
    try:
        vertexai.init(project=PROJECT_ID, location=REGION)
        # SFTでサポートされている基盤モデルのリストを取得
        supported_models = sft.train.supported_models
        
        print("✅ 【現在SFT（ファインチューニング）可能なGeminiモデル一覧】")
        for model in supported_models:
            print(f"  - {model}")
            
        print("\n💡 安定推奨: このリスト内に 'gemini-1.5-flash-002' があれば、それが蒸留（Distillation）に最適な最強のベースモデルです。")
        
    except AttributeError:
        print("⚠️ SDKのバージョンが古いか、取得メソッドが変更されています。確実に通るのは 'gemini-1.5-flash-002' および 'gemini-1.5-pro-002' です。")
    except Exception as e:
        print(f"🚨 エラーが発生しました: {e}")

if __name__ == "__main__":
    check_supported_models()

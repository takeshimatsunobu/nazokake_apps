import vertexai
from vertexai.tuning import sft

# --- 設定 ---
PROJECT_ID = "nazokakeapp-137e5"
REGION = "asia-northeast1"  # チューニングが未対応の場合は us-central1 等に変更が必要になる可能性があります
BUCKET_NAME = f"nazokake-training-data-{PROJECT_ID}"
LOCAL_FILE = "data/sft_dataset.jsonl"
GCS_FILE_PATH = f"gs://{BUCKET_NAME}/sft_dataset.jsonl"

BASE_MODEL = "gemini-3.1-flash" 

def start_tuning():
    print(f"🧠 Vertex AI ファインチューニングジョブの起動中... (ベース: {BASE_MODEL})")
    
    try:
        # Vertex AIの初期化
        vertexai.init(project=PROJECT_ID, location=REGION)
        
        # SFTジョブの作成と送信 (正しいモジュールを使用)
        sft_tuning_job = sft.train(
            source_model=BASE_MODEL,
            train_dataset=GCS_FILE_PATH,
            epochs=3,
            learning_rate_multiplier=1.0,
        )
        
        print("\n🎉 ジョブの送信に成功しました！")
        print(f"   ジョブ情報: {sft_tuning_job}")
        print("   Google Cloud Consoleの [Vertex AI] > [モデルレジストリ] または [チューニング] から進捗を確認できます。")
        
    except Exception as e:
        print(f"\n🚨 ジョブの送信中にGCP側からエラーが返されました:\n{e}")
        print("\n※考えられる原因: 指定したベースモデル（プレビュー版）またはリージョン（東京）が、SFTに未対応である可能性があります。")

if __name__ == "__main__":
    # バケットへのアップロードは先ほど成功しているためスキップし、ジョブ起動のみ行います
    start_tuning()

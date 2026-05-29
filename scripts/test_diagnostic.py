import time
from google.cloud import firestore
import requests

# 設定
db = firestore.Client()
WORKER_URL = "https://nazokake-worker-862686676938.asia-northeast1.run.app"
TEST_DOC_ID = "test_run_" + str(int(time.time()))

def run_diagnostic():
    print(f"🧪 [診断開始] テストID: {TEST_DOC_ID}")

    # 1. Firestoreへダミーデータ投入
    data = {
        "A_TITLE": "人工知能",
        "nazokake_text": "人工知能とかけて、新しいパソコンと解く。その心は、どちらも学習（再起動）が必要です。",
        "mode": "evaluate",
        "eval_status": "pending"
    }
    db.collection("nazokake_items").document(TEST_DOC_ID).set(data)
    print("✅ [STEP 1] ダミーデータ投入完了")

    # 2. ワーカーへ直接トリガーを送信（Eventarcの挙動を模倣）
    # Cloud Runのエンドポイントへ直接リクエスト
    headers = {"ce-subject": f"projects/nazokakeapp-137e5/databases/(default)/documents/nazokake_items/{TEST_DOC_ID}"}
    print(f"🚀 [STEP 2] ワーカーへ起動信号を送信中...")
    
    try:
        res = requests.post(WORKER_URL, headers=headers, timeout=60)
        print(f"📡 ワーカーの応答: {res.status_code}")
    except Exception as e:
        print(f"❌ ワーカー呼び出し失敗: {e}")
        return

    # 3. 結果の待ち受け
    print("⏳ [STEP 3] 評価結果を待機中...")
    for _ in range(10):
        time.sleep(5)
        doc = db.collection("nazokake_items").document(TEST_DOC_ID).get()
        if doc.exists and doc.get("eval_status") == "completed":
            print("🎉 [成功] AI評価が正常に完了しました！")
            print(f"総合点: {doc.get('s_total')}")
            print(f"AIの思考: {doc.get('reasoning')[:50]}...")
            return
        print("...")
    print("⚠️ タイムアウト: 評価が完了しませんでした。ログを確認してください。")

if __name__ == "__main__":
    run_diagnostic()

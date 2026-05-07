import base64
import json
import requests

# 1. テスト対象のドキュメントID (Firestoreに存在するテスト用IDを指定)
TARGET_DOCUMENT_ID = "test_doc_001" 
LOCAL_URL = "http://localhost:8080/"

def trigger_local_worker():
    """Pub/SubのPush通知を模倣したHTTP POSTリクエストをローカルサーバーに送信する"""
    
    # 実際のペイロードを作成し、Base64でエンコード
    payload_dict = {"document_id": TARGET_DOCUMENT_ID}
    payload_json = json.dumps(payload_dict).encode("utf-8")
    base64_data = base64.b64encode(payload_json).decode("utf-8")

    # Cloud Pub/Subが実際に送ってくるエンベロープ（包み紙）の構造
    pubsub_envelope = {
        "message": {
            "data": base64_data,
            "messageId": "mock-message-id-12345",
            "publishTime": "2023-10-01T00:00:00.000Z"
        }
    }

    print(f"[{TARGET_DOCUMENT_ID}] ローカルサーバーへモックリクエストを送信します...")
    
    try:
        response = requests.post(LOCAL_URL, json=pubsub_envelope)
        print(f"レスポンスステータス: {response.status_code}")
        if response.status_code == 200:
            print("✅ 成功: 処理が完了しました（またはACKされました）。")
        elif response.status_code == 500:
            print("⚠️ 一時的エラー: サーバーが500を返しました（Pub/Sub再送対象）。")
        else:
            print(f"❌ エラー: {response.text}")
    except requests.exceptions.ConnectionError:
        print("❌ サーバーに接続できません。uvicornが起動しているか確認してください。")

if __name__ == "__main__":
    trigger_local_worker()
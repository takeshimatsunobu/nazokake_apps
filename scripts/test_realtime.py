# scripts/test_realtime.py
import time
from google.cloud import firestore

def test_eventarc_pipeline():
    print("🚀 フロントエンドからの新規投稿をシミュレートします...")
    db = firestore.Client()
    
    # ユーザーが投稿したばかりの「未処理」なぞかけデータ
    mock_data = {
        "A_TITLE": "エンジニア",
        "B_TITLE": "魔法使い",
        "C_READING": "コード（呪文）をかく",
        "A_CONTEXT_DETAIL": "何もないところからシステムを作り出す様子",
        "GENERATION_TYPE": "テスト用データ",
        "nazokake_text": "エンジニアとかけて、魔法使いと解く。その心は、どちらも『コード（呪文）』を書いて世界を動かすでしょう。",
        "status": 0  # これがEventarcのトリガーになる！
    }

    # Firestoreに書き込み（ここでEventarcが自動発火するはず！）
    _, doc_ref = db.collection('nazokake_items').add(mock_data)
    print(f"📝 Firestoreに新規ドキュメントを作成しました: {doc_ref.id}")
    print("⏳ Eventarcが検知し、Cloud Run(Gemini)が評価するのを待っています (約10〜15秒)...")

    # Cloud Runが起動してGeminiが推論を終えるまで少し待つ
    time.sleep(12)

    # 結果を再取得して確認
    result = doc_ref.get().to_dict()
    status = result.get("status")

    print("\n" + "="*50)
    if status == 2:
        print("🎉 大成功！全自動AI評価パイプラインが完璧に動作しました！")
        print("📊 獲得スコア:")
        scores = result.get("scores", {})
        for key, val in scores.items():
            print(f"  - {key}: {val}")
    elif status == 1:
        print("🔄 現在AIが一生懸命評価中です（もう少し待ってからFirestoreを確認してください）。")
    elif status == 9:
        print(f"❌ エラーが発生しました。エラー内容: {result.get('error_message')}")
    else:
        print(f"🤔 ステータスは {status} のままです。Eventarcのトリガーがまだ有効になっていない可能性があります。")
    print("="*50)

if __name__ == "__main__":
    test_eventarc_pipeline()
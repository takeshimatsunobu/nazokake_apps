# scripts/check_doc.py
from google.cloud import firestore

def check_single_doc():
    db = firestore.Client()
    # 先ほどEventarcが検知したドキュメントID
    doc_id = "klIpQOQIdQDuWplcmYXe" 
    
    print(f"🔍 ドキュメント {doc_id} の最終結果を確認します...")
    result = db.collection('nazokake_items').document(doc_id).get().to_dict()

    status = result.get('status')
    print("\n" + "="*50)
    print(f"現在のステータス: {status}")
    
    if status == 2:
        print("🎉 完璧です！全自動AI評価パイプラインが開通しました！")
        print("📊 獲得スコア:")
        for key, val in result.get('scores', {}).items():
            print(f"  - {key}: {val}")
    elif status == 9:
        print(f"❌ エラーになっていました: {result.get('error_message')}")
    else:
        print("🔄 まだAIが考え中のようです。")
    print("="*50)

if __name__ == "__main__":
    check_single_doc()
    
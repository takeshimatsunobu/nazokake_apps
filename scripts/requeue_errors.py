# scripts/requeue_errors.py
import os
import logging
from google.cloud import firestore

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def requeue_errors():
    """
    status: 9 (エラー) のドキュメントを 0 (未処理) に戻し、リトライさせる
    """
    logger.info("エラードキュメント(status: 9)のリカバリーを開始します...")
    
    db = firestore.Client()
    # status が 9 のドキュメントのみを検索
    error_docs = db.collection('nazokake_items').where('status', '==', 9).stream()

    count = 0
    for doc in error_docs:
        # トランザクションは不要（エラー状態からの復帰のため）
        doc.reference.update({
            'status': 0,          # 未処理に戻す
            'retry_count': 0,     # リトライ回数をリセット
            'error_message': firestore.DELETE_FIELD  # エラーメッセージフィールドを削除
        })
        count += 1

    logger.info(f"✅ {count} 件のドキュメントを未処理(status: 0)にリセットしました！")
    logger.info("Cloud Runワーカーが自動的に処理を再開するか、必要に応じて publish_jobs.py を再実行してください。")

if __name__ == "__main__":
    requeue_errors()
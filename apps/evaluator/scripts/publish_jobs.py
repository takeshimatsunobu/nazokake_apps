from google.cloud.firestore_v1.base_query import FieldFilter
import concurrent.futures
import json
import logging
from google.cloud import firestore
from google.cloud import pubsub_v1

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# プロジェクトIDとトピック名（実行環境に合わせて調整してください）
PROJECT_ID = "nazokakeapp-137e5" 
TOPIC_ID = "nazokake-eval-topic"

def publish_jobs():
    """Firestoreの未処理データを抽出し、Pub/Subへ一括Publishする"""
    db = firestore.Client()
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)

    logger.info("Firestoreから未処理(status=0)のドキュメントを検索します...")
    
    # メモリ枯渇を防ぐため stream() を使用してカーソルベースで取得
    docs = db.collection("nazokake_items").where(filter=FieldFilter("status", "==", 0)).stream()

    publish_count = 0
    futures = []

    for doc in docs:
        payload = {"document_id": doc.id}
        data_bytes = json.dumps(payload).encode("utf-8")

        # Pub/Subへ非同期でPublish
        future = publisher.publish(topic_path, data=data_bytes)
        futures.append(future)
        publish_count += 1

        if publish_count % 1000 == 0:
            logger.info(f"{publish_count}件のメッセージをPublishしました...")

    # すべての非同期Publishがネットワーク送信を完了するまで待機
    if futures:
        concurrent.futures.wait(futures) 
           
    logger.info(f"✅ 合計 {publish_count} 件のジョブをPub/Subへキューイングしました。")

if __name__ == "__main__":
    publish_jobs()
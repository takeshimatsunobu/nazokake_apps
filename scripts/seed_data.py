import json
import logging
from google.cloud import firestore

# ログ設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Firestoreのバッチ書き込み上限は500件
BATCH_SIZE = 500

def seed_data(file_path: str):
    """JSONファイルからデータを読み込み、Firestoreにバッチインサートする"""
    db = firestore.Client()
    collection_ref = db.collection("nazokake_items")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"データファイルが見つかりません: {file_path}")
        return

    total = len(raw_data)
    logger.info(f"{total}件のデータをFirestoreへ投入開始します...")

    batch = db.batch()
    count = 0

    for item in raw_data:
        doc_ref = collection_ref.document() # FirestoreがIDを自動採番
        
        # 要件定義に基づく完全なスキーマ（初期値）
        doc_data = {
            "A_TITLE": item.get("A_TITLE", ""),
            "B_TITLE": item.get("B_TITLE", ""),
            "C_READING": item.get("C_READING", ""),
            "A_CONTEXT_DETAIL": item.get("A_CONTEXT_DETAIL", ""),
            "GENERATION_TYPE": item.get("GENERATION_TYPE", ""),
            "nazokake_text": item.get("nazokake_text", ""),
            "status": 0,  # 0: 未処理
            "retry_count": 0,
            "error_message": "",
            "scores": {
                "S_sur": 0.0, "S_nat": 0.0, "S_tech": 0.0, "S_emo": 0.0,
                "S_rhy": 0.0, "S_sensory": 0.0, "S_visual": 0.0,
                "S_ontology": 0.0, "S_cultural": 0.0, "S_cm": 0.0, "S_prosody": 0.0
            }
        }
        batch.set(doc_ref, doc_data)
        count += 1

        # 500件ごとにコミットしてバッチをリセット
        if count % BATCH_SIZE == 0:
            batch.commit()
            logger.info(f"{count} / {total} 件コミット完了...")
            batch = db.batch()

    # 端数の残りをコミット
    if count % BATCH_SIZE != 0:
        batch.commit()
        logger.info(f"{count} / {total} 件コミット完了...")

    logger.info("✅ 全てのデータ投入が完了しました。")

if __name__ == "__main__":
    # ※実行前に nazokake-evaluator/data/raw_data.json などに実データを配置してください
    # ここでは仮のパスを指定しています。
    seed_data("data/raw_data.json")

import os
import csv
import logging
from google.cloud import firestore

# ログの設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Firestoreクライアントの初期化
db = firestore.Client()

# CSVファイルのパス指定（画像で見えているパスに合わせています）
CSV_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "seisei_nazokake_bot - シート1.csv")
COLLECTION_NAME = "nazokake_items"

def seed_csv_to_firestore():
    if not os.path.exists(CSV_FILE_PATH):
        logger.error(f"CSVファイルが見つかりません: {CSV_FILE_PATH}")
        return

    batch = db.batch()
    batch_count = 0
    total_added = 0
    total_skipped = 0

    logger.info("CSVデータの読み込みとFirestoreへの投入を開始します...")

    # utf-8-sig を指定することで、Excelから出力したCSV特有のBOM（文字化け原因）を回避します
    with open(CSV_FILE_PATH, mode="r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            # ========================================================
            # ⚠️ 注意: CSVの1行目（ヘッダー）の列名と一致させる必要があります
            # もしCSVの列名が「お題A」などの日本語なら、row.get("お題A") に変更してください
            # ========================================================
            # CSVの日本語ヘッダー名と、Firestoreの英語キー名を紐づけます
            doc_data = {
                "A_TITLE": row.get("お題", ""),
                "B_TITLE": row.get("掛けた対象", ""),
                "C_READING": row.get("心の読み", ""),
                "A_CONTEXT_DETAIL": row.get("属性", ""),
                "nazokake_text": row.get("完成文章", ""),
                "GENERATION_TYPE": row.get("型", "CSVインポート"),
                "status": 0,          # 0: 未処理（AI評価の対象）
                "retry_count": 0
            }
            
            # 必須項目（完成文章など）が空の場合はスキップ
            if not doc_data["nazokake_text"]:
                total_skipped += 1
                continue

            # Firestoreに新しいドキュメント参照（ランダムID）を作成
            doc_ref = db.collection(COLLECTION_NAME).document()

            # バッチにセット
            batch.set(doc_ref, doc_data)
            batch_count += 1
            total_added += 1

            # 500件ごとにコミット（Firestoreの制限）
            if batch_count == 500:
                batch.commit()
                logger.info(f"✅ {total_added} 件コミット完了...")
                batch = db.batch()  # バッチをリセット
                batch_count = 0

    # 残りの端数をコミット
    if batch_count > 0:
        batch.commit()

    # 画像に映っていた完了ログ
    logger.info("========== 処理完了 ==========")
    logger.info(f"✅ 新規追加: {total_added} 件")
    logger.info(f"⏭️ 登録スキップ(空データ等): {total_skipped} 件")

if __name__ == "__main__":
    seed_csv_to_firestore()
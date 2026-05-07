import logging
from google.cloud import firestore

# ログ設定
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def seed_mock_data():
    """ローカルテスト用のモックデータをFirestoreに1件投入する"""
    db = firestore.Client()
    
    # テストで指定したドキュメントID
    target_id = "test_doc_001"
    doc_ref = db.collection("nazokake_items").document(target_id)
    
    # 要件定義に基づく完全なスキーマ
    mock_data = {
        "A_TITLE": "満員電車",
        "B_TITLE": "風邪をひいたときの鼻",
        "C_READING": "つまる",
        "A_CONTEXT_DETAIL": "人がぎっしり詰め込まれている様子",
        "GENERATION_TYPE": "完全な同音異義語型",
        "nazokake_text": "満員電車とかけて、風邪をひいたときの鼻と解く、その心は「どちらも詰まる」でしょう。",
        
        "status": 0,           # 0: 未処理
        "retry_count": 0,
        "error_message": "",
        
        "scores": {
            "S_sur": 0.0, "S_nat": 0.0, "S_tech": 0.0,
            "S_emo": 0.0, "S_rhy": 0.0, "S_sensory": 0.0,
            "S_visual": 0.0, "S_ontology": 0.0, "S_cultural": 0.0,
            "S_cm": 0.0, "S_prosody": 0.0
        }
    }
    
    doc_ref.set(mock_data)
    logger.info(f"✅ モックデータ '{target_id}' をFirestore (nazokake_items) に作成・初期化しました。")

if __name__ == "__main__":
    seed_mock_data()
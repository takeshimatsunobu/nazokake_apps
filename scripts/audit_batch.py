# scripts/audit_batch.py
import os
import logging
from collections import Counter
from google.cloud import firestore

# ロギング設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# 必須となる11軸のスコアキー
REQUIRED_SCORE_KEYS = {
    "S_sur", "S_nat", "S_tech", "S_emo", "S_rhy", 
    "S_sensory", "S_visual", "S_ontology", "S_cultural", 
    "S_cm", "S_prosody"
}

def audit_firestore_data():
    """
    Firestore上のなぞかけバッチ処理結果を監査し、標準出力にレポートする。
    """
    logger.info("Firestoreからのデータ取得および監査を開始します...")
    
    try:
        db = firestore.Client()
        # .stream()を使用し、ジェネレータとして順次取得（メモリ枯渇対策）
        docs = db.collection('nazokake_items').stream()
    except Exception as e:
        logger.error(f"Firestoreへの接続に失敗しました: {e}")
        return

    total_count = 0
    status_counts = Counter()
    missing_scores_count = 0
    error_reasons = Counter()

    for doc in docs:
        total_count += 1
        data = doc.to_dict()
        
        status = data.get('status', 0)
        status_counts[status] += 1

        if status == 2:
            # status: 2 (完了) の場合、11軸スコアの完全性をチェック
            scores = data.get('scores', {})
            if not REQUIRED_SCORE_KEYS.issubset(scores.keys()):
                missing_scores_count += 1
                logger.warning(f"ドキュメント {doc.id}: スコアキーに欠損があります。")
                
        elif status == 9:
            # status: 9 (エラー) の場合、エラーメッセージの傾向を集計
            error_msg = data.get('error_message', 'No error message provided')
            short_error = error_msg[:60].strip() # ログ集計用に先頭60文字で丸める
            error_reasons[short_error] += 1

    # レポート出力
    print("\n" + "="*50)
    print("📊 バッチ処理監査レポート")
    print("="*50)
    print(f"総スキャン件数: {total_count} 件")
    print(f"[0] 未処理: {status_counts.get(0, 0)} 件")
    print(f"[1] 処理中: {status_counts.get(1, 0)} 件")
    print(f"[2] 完了　: {status_counts.get(2, 0)} 件")
    print(f"[9] エラー: {status_counts.get(9, 0)} 件")
    print("-" * 50)
    
    if missing_scores_count > 0:
        print(f"⚠️ スコア欠損ドキュメント数: {missing_scores_count} 件")
    else:
        print("✅ スコア欠損: 0 件 (すべての完了データが正常です)")

    if error_reasons:
        print("\n🔥 エラー原因（status: 9）の内訳:")
        for reason, count in error_reasons.items():
            print(f"  - {count}件: {reason}...")
    print("="*50)

if __name__ == "__main__":
    audit_firestore_data()
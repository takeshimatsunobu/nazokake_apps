from google.cloud import firestore
import logging

logger = logging.getLogger(__name__)
db = firestore.Client()

@firestore.transactional
def lock_document_for_processing(transaction, doc_ref):
    """
    冪等性の担保: ドキュメントを読み込み、未処理(0)の場合のみ処理中(1)にロックする。
    """
    snapshot = doc_ref.get(transaction=transaction)
    if not snapshot.exists:
        return False, None

    data = snapshot.to_dict()
    status = data.get("status", 0)

    # 既に処理中(1)や完了(2)のメッセージが重複して届いた場合はスキップ
    if status != 0:
        logger.info(f"ドキュメント {doc_ref.id} は既に処理済みです(status: {status})。スキップします。")
        return False, data

    # トランザクション内でステータスを1に更新（排他ロック完了）
    transaction.update(doc_ref, {"status": 1})
    return True, data

def save_evaluation_success(doc_id: str, scores: dict):
    """正常完了時のスコア保存"""
    doc_ref = db.collection("nazokake_items").document(doc_id)
    doc_ref.update({
        "status": 2,
        "scores": scores
    })

@firestore.transactional
def handle_evaluation_error(transaction, doc_ref, error_message: str):
    """
    エラー時のリトライ制御。3回未満ならステータスを0に戻して再送を促し、
    3回以上ならエラー(9)としてロックする。
    """
    snapshot = doc_ref.get(transaction=transaction)
    data = snapshot.to_dict()
    retry_count = data.get("retry_count", 0) + 1

    if retry_count >= 3:
        transaction.update(doc_ref, {
            "status": 9,
            "retry_count": retry_count,
            "error_message": str(error_message)
        })
        return False  # 再送不要フラグ
    else:
        # リトライ可能な場合はステータスを0に戻し、次回ワーカーが拾えるようにする
        transaction.update(doc_ref, {
            "status": 0,
            "retry_count": retry_count
        })
        return True  # 再送要求フラグ
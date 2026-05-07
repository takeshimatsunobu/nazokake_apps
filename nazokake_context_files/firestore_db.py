from google.cloud import firestore
import logging
from gemini_api import evaluate_nazokake

db = firestore.Client()
logger = logging.getLogger(__name__)

@firestore.transactional
def lock_document_in_transaction(transaction, doc_ref):
    snapshot = doc_ref.get(transaction=transaction)
    if not snapshot.exists:
        return None
    
    data = snapshot.to_dict()
    if data.get("status", 0) != 0:
        return False
        
    transaction.update(doc_ref, {"status": 1})
    return data

async def process_nazokake_document(document_id: str) -> bool:
    doc_ref = db.collection("nazokake_items").document(document_id)
    transaction = db.transaction()
    
    try:
        doc_data = lock_document_in_transaction(transaction, doc_ref)
        
        if doc_data is False:
            logger.info(f"Doc {document_id} は既に処理中/完了済みです（重複検知）")
            return True 
        if doc_data is None:
            return True 
            
        evaluation_scores = await evaluate_nazokake(doc_data)
        
        doc_ref.update({
            "status": 2,
            "scores": evaluation_scores
        })
        logger.info(f"Doc {document_id} の評価が正常完了しました")
        return True
        
    except Exception as e:
        logger.error(f"Doc {document_id} 処理中にエラー発生: {e}")
        doc_ref.update({
            "status": 9,
            "error_message": str(e)
        })
        return True

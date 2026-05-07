# main.py
from fastapi import FastAPI, Request, Response
import base64
import json
import logging
from firestore_db import lock_document_for_processing, save_evaluation_success, handle_evaluation_error, db
from gemini_api import evaluate_with_gemini

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn")

@app.post("/")
async def worker_endpoint(request: Request):
    """Eventarc(リアルタイム)とPub/Sub(バッチ)の両方を受け付けるハイブリッドエンドポイント"""
    doc_id = None

    # --- 1. Eventarcからのリアルタイム検知 (CloudEvents形式) ---
    # EventarcはHTTPヘッダーの 'ce-subject' にドキュメントのパスを入れて送ってきます
    ce_subject = request.headers.get("ce-subject")
    if ce_subject:
        # 例: projects/.../databases/(default)/documents/nazokake_items/DOC_ID
        doc_id = ce_subject.split("/")[-1]
        logger.info(f"⚡ Eventarcリアルタイム検知: {doc_id}")
        
    # --- 2. Pub/Subからのバッチ検知 (従来形式) ---
    else:
        try:
            envelope = await request.json()
            if "message" in envelope and "data" in envelope["message"]:
                data_json = base64.b64decode(envelope["message"]["data"]).decode("utf-8")
                payload = json.loads(data_json)
                doc_id = payload.get("document_id")
                logger.info(f"📦 Pub/Subバッチ検知: {doc_id}")
        except Exception as e:
            logger.error(f"ペイロードのパースエラー: {e}")
            return Response(status_code=200)

    # どちらの経路でも doc_id が取れなかった場合は終了
    if not doc_id:
        return Response(status_code=200, content="No Document ID found")

    # --- 3. 共通の評価フロー（変更なし） ---
    # 1. トランザクションによる排他ロック (冪等性の担保)
    doc_ref = db.collection("nazokake_items").document(doc_id)
    transaction = db.transaction()
    is_locked, doc_data = lock_document_for_processing(transaction, doc_ref)
    
    if not is_locked:
        return Response(status_code=200)

    try:
        # 2. AI呼び出し
        logger.info(f"ドキュメント {doc_id} のAI評価を開始します...")
        scores = evaluate_with_gemini(doc_data)
        
        # 3. 正常完了の保存
        save_evaluation_success(doc_id, scores)
        logger.info(f"✅ ドキュメント {doc_id} の評価が完了しました。")
        return Response(status_code=200)

    except Exception as e:
        # 4. エラーハンドリングとリトライ制御
        logger.error(f"❌ ドキュメント {doc_id} の処理中にエラー: {e}")
        transaction = db.transaction()
        should_retry = handle_evaluation_error(transaction, doc_ref, str(e))
        
        if should_retry:
             return Response(status_code=500, content="Internal Server Error - Retry requested")
        else:
             return Response(status_code=200, content="Max retries reached")
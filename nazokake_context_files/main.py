import base64
import json
import logging
from fastapi import FastAPI, Request, Response, status
from firestore_db import process_nazokake_document

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

@app.post("/")
async def pubsub_push(request: Request):
    try:
        envelope = await request.json()
    except Exception:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    pubsub_message = envelope.get("message")
    if not pubsub_message or "data" not in pubsub_message:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    try:
        decoded_data = base64.b64decode(pubsub_message["data"]).decode("utf-8")
        payload = json.loads(decoded_data)
        document_id = payload.get("document_id")
    except Exception as e:
        logger.error(f"ペイロードのパースエラー: {e}")
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    if not document_id:
        return Response(status_code=status.HTTP_200_OK)

    success = await process_nazokake_document(document_id)

    if success:
        return Response(status_code=status.HTTP_200_OK)
    else:
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

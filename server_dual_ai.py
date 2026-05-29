import os
import json
import logging
import requests
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import firebase_admin
from firebase_admin import credentials as firebase_credentials, firestore
import google.generativeai as genai
from google.oauth2 import service_account
import google.auth.transport.requests as google_requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Nazokake Dual AI Backend")
os.makedirs("frontend", exist_ok=True)
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

try:
    cred = firebase_credentials.Certificate("serviceAccountKey.json")
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    logger.info("🔥 Firebase initialized successfully.")
except Exception as e:
    logger.error(f"🚨 Firebase init error: {e}")
    db = None

try:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and os.path.exists('gemini_api_key.json'):
        with open('gemini_api_key.json', 'r') as f:
            api_key = json.load(f).get('api_key')
    if api_key:
        genai.configure(api_key=api_key)
        logger.info("💎 Gemini API configured successfully.")
except Exception:
    pass

try:
    vertex_creds = service_account.Credentials.from_service_account_file(
        'serviceAccountKey.json', scopes=['https://www.googleapis.com/auth/cloud-platform'])
    logger.info("🚀 Vertex AI Credentials loaded successfully.")
except Exception:
    vertex_creds = None

class EvaluateRequest(BaseModel): doc_id: str; user_score: int
class HumanSubmitRequest(BaseModel): odai: str; nazokake_text: str; parent_id: Optional[str] = None
class GenerateRequest(BaseModel): odai: str

@app.get("/")
def read_root(): return FileResponse("frontend/index.html")

@app.get("/api/feed")
def get_feed():
    if not db: raise HTTPException(status_code=500, detail="DB Error")
    docs = db.collection("nazokake_items").limit(50).stream()
    all_items = [{"doc_id": d.id, **d.to_dict()} for d in docs]
    import random
    random_items = random.sample(all_items, min(10, len(all_items)))
    scored_items = []
    for item in all_items:
        human_evals = [e.get("user_score", 0) for e in item.get("user_evaluations", []) if not e.get("is_synthetic")]
        if human_evals: scored_items.append((sum(human_evals)/len(human_evals), item))
    scored_items.sort(key=lambda x: x[0], reverse=True)
    return {"top10": [i for a, i in scored_items[:10]], "random": random_items, "golden": [i for a, i in scored_items if a >= 4.5]}

@app.post("/api/submit_human")
def submit_human(req: HumanSubmitRequest):
    if not db: raise HTTPException(status_code=500, detail="DB Error")
    model = genai.GenerativeModel("gemini-3-flash-preview")
    prompt = f"あなたは厳格な審査員です。以下のなぞかけを12軸で0.0~1.0で評価しJSONで出力してください。\nお題: {req.odai} \n作品: {req.nazokake_text} \n出力例: {{\"scores\": {{\"S_tech\": 0.8, \"S_sur\": 0.8, \"S_humor\": 0.8, \"S_cm\": 0.8, \"S_prosody\": 0.8, \"S_cultural\": 0.8, \"S_visual\": 0.8, \"S_rhy\": 0.8, \"S_emo\": 0.8, \"S_ontology\": 0.8, \"S_sensory\": 0.8}}, \"reasoning\": \"理由\"}}"
    resp_text = model.generate_content(prompt).text.replace('```json', '').replace('```', '').strip()
    doc_ref = db.collection("nazokake_items").document()
    doc_ref.set({"A_TITLE": req.odai, "nazokake_text": req.nazokake_text, "scores": json.loads(resp_text).get("scores", {}), "reasoning": json.loads(resp_text).get("reasoning", ""), "author": "Human", "parent_id": req.parent_id, "timestamp": firestore.SERVER_TIMESTAMP})
    return {"status": "success", "doc_id": doc_ref.id}

@app.post("/api/evaluate")
def evaluate_item(req: EvaluateRequest):
    if not db: raise HTTPException(status_code=500, detail="DB Error")
    db.collection("nazokake_items").document(req.doc_id).update({"user_evaluations": firestore.ArrayUnion([{"timestamp": datetime.now(timezone.utc).isoformat(), "user_score": req.user_score, "is_synthetic": False}])})
    return {"status": "success"}

@app.post("/api/generate_ai")
def generate_ai(req: GenerateRequest):
    if not vertex_creds: raise HTTPException(status_code=500, detail="Vertex Error")
    req_auth = google_requests.Request()
    vertex_creds.refresh(req_auth)
    url = "https://us-central1-aiplatform.googleapis.com/v1/projects/862686676938/locations/us-central1/endpoints/2995325310515281920:generateContent"
    prompt = f"あなたは「なぞかけ」の達人です。以下の書き出しに続けて、「〇〇と解く。その心は、どちらも□□でしょう。」という形でオチを完成させてください。※解説は絶対に出力しないでください。\n書き出し:\n「{req.odai}」とかけて、"
    res = requests.post(url, headers={"Authorization": f"Bearer {vertex_creds.token}", "Content-Type": "application/json"}, json={"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.5}})
    text = res.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
    return {"status": "success", "nazokake": text if text.startswith("「" + req.odai) else f"「{req.odai}」とかけて、\n{text}"}


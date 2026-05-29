from fastapi import APIRouter, HTTPException, BackgroundTasks
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import firestore
from models.schemas import EvaluateRequest, HumanSubmitRequest, GenerateRequest
from services.ai_service import evaluate_and_update_task, generate_nazokake
import random

router = APIRouter()
db = firestore.client()

def serialize_doc(doc):
    data = doc.to_dict()
    data["doc_id"] = doc.id
    if "timestamp" in data and isinstance(data["timestamp"], datetime):
        data["timestamp"] = str(data["timestamp"])
    return data

@router.get("/feed")
def get_feed():
    try:
        docs = db.collection("nazokake_items").limit(50).stream()
        all_items = [serialize_doc(d) for d in docs]
        
        random_items = random.sample(all_items, min(10, len(all_items)))
        
        scored_items = []
        for item in all_items:
            evals = item.get("user_evaluations", [])
            human_evals = [e.get("user_score", 0) for e in evals if not e.get("is_synthetic")]
            if human_evals:
                avg = sum(human_evals) / len(human_evals)
                scored_items.append((avg, item))
                
        scored_items.sort(key=lambda x: x[0], reverse=True)
        top10 = [item for avg, item in scored_items[:10]]
        golden = [item for avg, item in scored_items if avg >= 4.5]

        return {"top10": top10, "random": random_items, "golden": golden}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@router.get("/dojo_arena")
def get_dojo_arena():
    try:
        docs = db.collection("nazokake_items").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(100).stream()
        all_items = [serialize_doc(d) for d in docs]
        
        arena_items = random.sample(all_items, min(30, len(all_items)))
        return {"arena_items": arena_items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@router.post("/submit_human")
def submit_human(req: HumanSubmitRequest, background_tasks: BackgroundTasks):
    try:
        doc_ref = db.collection("nazokake_items").document()
        doc_ref.set({
            "A_TITLE": req.odai,
            "nazokake_text": req.nazokake_text,
            "author": "Human",
            "parent_id": req.parent_id,
            "is_sft_data": bool(req.parent_id),
            "timestamp": firestore.SERVER_TIMESTAMP,
            "eval_status": "processing",
            "s_total": 0.0
        })
        
        background_tasks.add_task(evaluate_and_update_task, db, doc_ref.id, req.odai, req.nazokake_text)
        return {"status": "processing", "doc_id": doc_ref.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@router.get("/status/{doc_id}")
def get_status(doc_id: str):
    try:
        doc = db.collection("nazokake_items").document(doc_id).get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Document not found")
        data = serialize_doc(doc)
        return {
            "eval_status": data.get("eval_status", "unknown"),
            "s_total": data.get("s_total", 0.0),
            "scores": data.get("scores", {})
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@router.post("/evaluate")
def evaluate_item(req: EvaluateRequest):
    try:
        doc_ref = db.collection("nazokake_items").document(req.doc_id)
        eval_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_score": req.user_score,
            "is_synthetic": False,
            "source": "human_web_ui"
        }
        doc_ref.update({"user_evaluations": firestore.ArrayUnion([eval_data])})
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@router.post("/generate_ai")
def generate_ai(req: GenerateRequest):
    try:
        result = generate_nazokake(req.odai)
        return {"status": "success", "nazokake": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
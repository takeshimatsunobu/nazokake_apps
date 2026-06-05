import os
import html
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from datetime import datetime, timezone, timedelta
from firebase_admin import firestore
from models.schemas import EvaluateRequest, HumanSubmitRequest, GenerateRequest, TelemetryLogRequest
from pydantic import BaseModel
import random
from functools import wraps
from typing import Callable, Any, Optional
import asyncio
import inspect
from services.ai_service import evaluate_and_update_task, generate_nazokake

router = APIRouter()
admin_db = firestore.Client()

# 🚨 新規追加: フィードバック受信用スキーマ
class FeedbackRequest(BaseModel):
    score: int
    comment: str
    user_slug: str = "anonymous"

class LoginRequest(BaseModel):
    username: str = None
    password: str

class ConfigUpdateRequest(BaseModel):
    temperature: float
    model_name: str
    system_prompt: str

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "himitsu")
ADMIN_TOKEN = "admin_token_secret_123"

def verify_admin(authorization: str = Header(None)):
    if not authorization or authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

def serialize_doc(doc) -> dict:
    data = doc.to_dict()
    data["doc_id"] = doc.id
    data["id"] = doc.id
    if "timestamp" in data and isinstance(data["timestamp"], datetime):
        data["timestamp"] = str(data["timestamp"])
    return data

def handle_exceptions(func: Callable) -> Callable:
    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            try: return await func(*args, **kwargs)
            except HTTPException: raise
            except Exception as e: return {"status": "error", "message": f"Internal Server Error: {str(e)}"}
        return async_wrapper
    else:
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            try: return func(*args, **kwargs)
            except HTTPException: raise
            except Exception as e: raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
        return sync_wrapper

# --- 管理者API ---
@router.post("/admin/login")
def admin_login(req: LoginRequest):
    if req.password == ADMIN_PASSWORD: return {"token": ADMIN_TOKEN}
    raise HTTPException(status_code=401, detail="Invalid password")

@router.get("/admin/config")
def get_config(auth: None = Depends(verify_admin)):
    doc = admin_db.collection("system_configs").document("ai_settings").get()
    if doc.exists: return doc.to_dict()
    return {"temperature": 0.8, "model_name": "gemini-1.5-flash", "system_prompt": "あなたは前衛的な天才なぞかけ芸人です。"}

@router.post("/admin/config")
def update_config(req: ConfigUpdateRequest, auth: None = Depends(verify_admin)):
    admin_db.collection("system_configs").document("ai_settings").set(req.model_dump())
    return {"status": "success"}

@router.get("/admin/pending")
def get_pending(auth: None = Depends(verify_admin)):
    docs = admin_db.collection("nazokake_items").where("is_user_edited", "==", True).stream()
    items = []
    for doc in docs:
        data = serialize_doc(doc)
        if not data.get("is_golden_data"): items.append(data)
    return {"items": sorted(items, key=lambda x: x.get("timestamp", ""), reverse=True)}

@router.post("/admin/approve/{doc_id}")
def approve_item(doc_id: str, auth: None = Depends(verify_admin)):
    admin_db.collection("nazokake_items").document(doc_id).update({"is_golden_data": True})
    return {"status": "success"}

@router.delete("/admin/delete/{doc_id}")
def delete_item(doc_id: str, auth: None = Depends(verify_admin)):
    admin_db.collection("nazokake_items").document(doc_id).delete()
    return {"status": "success"}

@router.post("/admin/reset/{doc_id}")
def reset_item(doc_id: str, auth: None = Depends(verify_admin)):
    doc_ref = admin_db.collection("nazokake_items").document(doc_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Item not found")
    data = doc.to_dict()
    orig = data.get("original_data")
    
    update_data = {
        "is_user_edited": False,
        "human_evaluations": firestore.DELETE_FIELD
    }
    
    if orig:
        update_data["A_TITLE"] = orig.get("odai", "")
        update_data["odai"] = orig.get("odai", "")
        update_data["result"] = orig.get("result", {})
        update_data["s_total"] = orig.get("s_total", 0.0)
        update_data["total_score"] = orig.get("s_total", 0.0)
        update_data["nazokake_text"] = orig.get("nazokake_text", "")
        
    doc_ref.update(update_data)
    return {"status": "success"}

@router.get("/admin/metrics")
@handle_exceptions
def get_admin_metrics(auth: None = Depends(verify_admin)):
    docs = admin_db.collection("telemetry_logs").stream()
    total_pv = 0; unique_users = set(); event_counts = {}; total_duration = 0.0; duration_count = 0
    for doc in docs:
        data = doc.to_dict()
        evt = data.get("event_name", ""); slug = data.get("user_slug", ""); dur = data.get("duration", 0.0)
        if evt in ["page_view", "tab_click"]: total_pv += 1
        if slug: unique_users.add(slug)
        if evt: event_counts[evt] = event_counts.get(evt, 0) + 1
        if evt == "page_leave" and dur > 0:
            total_duration += dur; duration_count += 1
    avg_dur = total_duration / duration_count if duration_count > 0 else 0.0
    return {"total_pvs": total_pv, "total_uus": len(unique_users), "avg_duration_sec": round(avg_dur, 1), "events": event_counts}

# --- 一般機能API ---
async def generate_and_update_task(doc_id: str, odai: str):
    try:
        parsed_result = await generate_nazokake(odai)
        toku = parsed_result.get("toku", ""); kokoro = parsed_result.get("kokoro", "")
        nazokake_text = f"「{odai}」とかけて、「{toku}」と解く。\nその心は、{kokoro}"
        await asyncio.to_thread(admin_db.collection("nazokake_items").document(doc_id).update, {"result": parsed_result, "message": "鑑定中..."})
        await evaluate_and_update_task(admin_db, doc_id, odai, nazokake_text)
    except Exception as e:
        await asyncio.to_thread(admin_db.collection("nazokake_items").document(doc_id).update, {"status": "error", "message": str(e)})

@router.get("/status/{doc_id}")
@handle_exceptions
def get_status(doc_id: str):
    doc = admin_db.collection("nazokake_items").document(doc_id).get()
    if not doc.exists: raise HTTPException(status_code=404, detail="Not found")
    data = serialize_doc(doc)
    return {"status": data.get("status", "unknown"), "eval_status": data.get("eval_status", "unknown"), "message": data.get("message", ""), "result": data.get("result", {}), "scores": data.get("scores", {}), "reasoning": data.get("reasoning", ""), "s_total": data.get("s_total", 0.0)}

@router.post("/generate")
@handle_exceptions
async def generate_ai(req: GenerateRequest):
    doc_ref = admin_db.collection("nazokake_items").document()
    doc_ref.set({"odai": req.odai, "status": "processing", "message": "AIが生成中...", "timestamp": firestore.SERVER_TIMESTAMP})
    await generate_and_update_task(doc_ref.id, req.odai)
    return {"status": "processing", "task_id": doc_ref.id}

@router.post("/submit_human")
@handle_exceptions
async def submit_human(req: HumanSubmitRequest):
    doc_ref = admin_db.collection("nazokake_items").document()
    doc_ref.set({"A_TITLE": req.odai, "nazokake_text": req.nazokake_text, "author": "Human", "parent_id": req.parent_id, "is_sft_data": bool(req.parent_id), "timestamp": firestore.SERVER_TIMESTAMP, "status": "processing", "eval_status": "processing", "s_total": 0.0})
    await evaluate_and_update_task(admin_db, doc_ref.id, req.odai, req.nazokake_text)
    return {"status": "processing", "doc_id": doc_ref.id}

@router.get("/feed/items")
async def get_user_feed(last_doc_id: Optional[str] = None, limit: int = 5):
    try:
        docs = admin_db.collection("nazokake_items").where("status", "==", "completed").stream()
        all_items = []
        for doc in docs:
            data = serialize_doc(doc)
            if not data.get("is_user_edited", False) and not data.get("is_golden_data", False):
                all_items.append(data)
        all_items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        start_idx = 0
        if last_doc_id:
            for i, item in enumerate(all_items):
                if item["doc_id"] == last_doc_id:
                    start_idx = i + 1
                    break
        return {"items": all_items[start_idx : start_idx + limit]}
    except Exception as e: return {"items": []}

@router.get("/feed/golden")
async def get_golden_feed(last_doc_id: Optional[str] = None, limit: int = 5):
    try:
        docs = admin_db.collection("nazokake_items").where("is_golden_data", "==", True).stream()
        all_items = [serialize_doc(doc) for doc in docs]
        all_items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        start_idx = 0
        if last_doc_id:
            for i, item in enumerate(all_items):
                if item["doc_id"] == last_doc_id:
                    start_idx = i + 1
                    break
        return {"items": all_items[start_idx : start_idx + limit]}
    except Exception as e: return {"items": []}

@router.post("/feed/evaluate/{doc_id}")
async def evaluate_user_item(doc_id: str, request: Request):
    try:
        data = await request.json()
        odai = html.escape(str(data.get("odai", "") or "").strip())
        toku = html.escape(str(data.get("toku", "") or "").strip())
        kokoro = html.escape(str(data.get("kokoro", "") or "").strip())
        if len(odai) < 1 or len(toku) < 1 or len(kokoro) < 1: raise HTTPException(status_code=400, detail="入力が短すぎます")
        if odai.lower() == "e" or toku.lower() == "e" or kokoro.lower() == "e": raise HTTPException(status_code=400, detail="不正な入力を検知しました")

        score = float(data.get("s_total", 0.0))
        user_slug = data.get("user_slug", "anonymous")

        doc_ref = admin_db.collection("nazokake_items").document(doc_id)
        doc = doc_ref.get()
        if not doc.exists: raise HTTPException(status_code=404, detail="Item not found")

        doc_data = doc.to_dict()
        if not doc_data.get("is_user_edited"):
            orig_data = {"odai": doc_data.get("odai", doc_data.get("A_TITLE", "")), "result": doc_data.get("result", {}), "s_total": doc_data.get("s_total", 0.0), "nazokake_text": doc_data.get("nazokake_text", "")}
            doc_ref.update({"original_data": orig_data})

        evaluations = doc_data.get("human_evaluations", {})
        evaluations[user_slug] = score 
        new_s_total = sum(evaluations.values()) / len(evaluations)

        fixed_text = f"「{odai}」とかけて、「{toku}」と解く。\nその心は、{kokoro}"
        update_data = {"A_TITLE": odai, "result": {"toku": toku, "kokoro": kokoro}, "total_score": new_s_total, "s_total": new_s_total, "nazokake_text": fixed_text, "is_user_edited": True, "human_evaluations": evaluations}
        doc_ref.set(update_data, merge=True)
        return {"message": "Success"}
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@router.post("/metrics/log")
@handle_exceptions
def log_telemetry(req: TelemetryLogRequest):
    admin_db.collection("telemetry_logs").document().set({"user_slug": req.user_slug, "event_name": req.event_name, "duration": req.duration, "tab_name": req.tab_name, "timestamp": firestore.SERVER_TIMESTAMP})
    return {"status": "success"}

# 🚨 新規追加: ご意見箱(フィードバック)受付API
@router.post("/feedback")
@handle_exceptions
def submit_feedback(req: FeedbackRequest):
    clean_comment = html.escape(str(req.comment or "").strip())
    admin_db.collection("app_feedbacks").document().set({
        "score": req.score,
        "comment": clean_comment,
        "user_slug": req.user_slug,
        "status": 0, # 0 = 未対応
        "created_at": firestore.SERVER_TIMESTAMP
    })
    return {"status": "success"}

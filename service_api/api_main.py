import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from google.cloud import firestore
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Nazokake Reception API")

# CORS設定（画面からの通信を許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = firestore.Client()

# --- データの受け取りフォーマット定義 ---
class GenerateRequest(BaseModel):
    odai: str

class SubmitHumanRequest(BaseModel):
    odai: str
    nazokake_text: str
    parent_id: Optional[str] = None

class EvaluateRequest(BaseModel):
    doc_id: str
    user_score: float

# --- エンドポイント（受付窓口） ---

@app.post("/api/generate_ai")
async def api_generate_ai(req: GenerateRequest):
    """AIに一からなぞかけを作らせる窓口"""
    doc_ref = db.collection("nazokake_items").document()
    doc_ref.set({
        "A_TITLE": req.odai,
        "status": 0,  # 0にすることで、ワーカー(Gemini)が自動的に起きる
        "mode": "create",
        "created_at": firestore.SERVER_TIMESTAMP
    })
    return {"doc_id": doc_ref.id, "message": "Generation started"}

@app.post("/api/submit_human")
async def api_submit_human(req: SubmitHumanRequest):
    """人間が作った（または編集した）なぞかけをAIに審査させる窓口"""
    doc_ref = db.collection("nazokake_items").document()
    data = {
        "A_TITLE": req.odai,
        "nazokake_text": req.nazokake_text,
        "status": 0,
        "mode": "evaluate",
        "created_at": firestore.SERVER_TIMESTAMP,
        "is_human_made": True
    }
    if req.parent_id:
        data["parent_doc_id"] = req.parent_id
        
    doc_ref.set(data)
    return {"doc_id": doc_ref.id, "message": "Evaluation started"}

@app.post("/api/evaluate")
async def api_evaluate(req: EvaluateRequest):
    """ユーザーが画面から入力した「星評価(RLHF)」を保存する窓口"""
    doc_ref = db.collection("nazokake_items").document(req.doc_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="対象のなぞかけが見つかりません")
    
    # 💡 ここが最重要！画面からの user_score を FINAL_SCORE_HUMAN として保存
    doc_ref.update({
        "FINAL_SCORE_HUMAN": req.user_score,
        "user_evaluations": firestore.ArrayUnion([{
            "user_score": req.user_score,
            "is_synthetic": False,
            "timestamp": firestore.SERVER_TIMESTAMP
        }])
    })
    return {"status": "success", "message": "RLHF evaluation successfully saved"}

@app.get("/api/dojo_arena")
async def api_dojo_arena():
    """タイムライン（フィード）用のデータを返す窓口"""
    # 評価が完了している最新50件を取得
    docs = db.collection("nazokake_items").where("status", "==", 2).order_by("created_at", direction=firestore.Query.DESCENDING).limit(50).stream()
    items = []
    for doc in docs:
        d = doc.to_dict()
        d["doc_id"] = doc.id
        items.append(d)
    return {"arena_items": items}

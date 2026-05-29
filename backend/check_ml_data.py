import firebase_admin
from firebase_admin import firestore
import json

if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.client()

docs = db.collection("nazokake_items").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(50).stream()

rlhf_count = 0
sft_count = 0

for doc in docs:
    data = doc.to_dict()
    
    # 1. RLHF（星評価）のチェック
    evals = data.get("user_evaluations", [])
    human_evals = [e for e in evals if not e.get("is_synthetic")]
    if human_evals:
        rlhf_count += 1

    # 2. SFT（道場破り）のチェック
    if data.get("is_sft_data") or data.get("parent_id"):
        sft_count += 1

print(f"直近50件の統計 -> RLHFデータ: {rlhf_count}件 / SFTデータ: {sft_count}件")
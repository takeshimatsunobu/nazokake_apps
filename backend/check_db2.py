import firebase_admin
from firebase_admin import firestore
import json

if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.client()
docs = db.collection("nazokake_items").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(1).stream()

for doc in docs:
    data = doc.to_dict()
    print(json.dumps(data, indent=2, default=str, ensure_ascii=False))
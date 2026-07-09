"""一時診断: board_posts の総件数をカウント（Read-Only・使い捨て）。"""

import firebase_admin
from firebase_admin import firestore as admin_firestore

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})

db = admin_firestore.client()
docs = db.collection("board_posts").stream()
count = sum(1 for _ in docs)
print(f"=== board_posts TOTAL count: {count} ===")

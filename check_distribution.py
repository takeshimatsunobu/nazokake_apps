import os
from pathlib import Path
from collections import Counter
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

def check_score_distribution():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    print("🚀 Firestoreから status:2 のデータ分布を調査中...")
    
    # 警告が出ないようにFieldFilterを使用
    docs = db.collection("nazokake_items").where(filter=FieldFilter("status", "==", 2)).stream()
    
    scores = []
    for doc in docs:
        data = doc.to_dict()
        scores.append(data.get("user_score", 0))
        
    distribution = Counter(scores)
    
    print("\n📊 【user_score（人間の評価）の分布状況】")
    total = 0
    for score, count in sorted(distribution.items()):
        print(f"  スコア {score}: {count}件")
        total += count
        
    print(f"  --- 合計: {total}件 ---")
    
    print("\n💡 学習データ抽出の目安:")
    print(f"  スコア4以上 (v2基準) の件数: {sum(c for s, c in distribution.items() if s >= 4)}件")
    print(f"  スコア3以上 (v4基準) の件数: {sum(c for s, c in distribution.items() if s >= 3)}件")

if __name__ == "__main__":
    check_score_distribution()

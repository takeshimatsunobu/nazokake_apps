import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path
from collections import Counter

def audit_firestore_full():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    print("🚀 Firestoreの全ドキュメントを網羅的に監査中（隠れたデータを探索）...")
    
    # statusの条件を外し、コレクション内のドキュメントを最大100件サンプル抽出してフィールド構造を解析
    docs_sample = db.collection("nazokake_items").limit(100).stream()
    
    all_fields = set()
    for doc in docs_sample:
        all_fields.update(doc.to_dict().keys())
        
    print("\n📋 【検知されたドキュメント内のフィールド一覧】")
    for field in sorted(all_fields):
        print(f"  - {field}")

    # コレクション内の全ドキュメントのステータス分布を調査
    print("\n📊 【インフラ上の全 status の分布状況】")
    all_docs = db.collection("nazokake_items").stream()
    
    status_counter = Counter()
    human_score_fields = ['user_score', 'FINAL_SCORE_HUMAN', 'human_score', 'score']
    detected_scores = {f: 0 for f in human_score_fields}
    
    total_count = 0
    for doc in all_docs:
        total_count += 1
        data = doc.to_dict()
        
        # ステータスをカウント
        status_val = data.get("status", "未定義")
        status_counter[status_val] += 1
        
        # 人間の評価が入っていそうな主要フィールドに、0かNone以外の値があるかチェック
        for field in human_score_fields:
            val = data.get(field)
            if val is not None and val != 0 and val != 0.0:
                detected_scores[field] += 1

    for stat, count in sorted(status_counter.items()):
        print(f"  - status {stat}: {count}件")
    print(f"  --- 総ドキュメント数: {total_count}件 ---")

    print("\n🎯 【人間が評価した形跡の捜索結果（0 or None 以外の件数）】")
    for field, count in detected_scores.items():
        print(f"  - フィールド '{field}': {count}件に有効な値を発見")
        
    if sum(detected_scores.values()) == 0:
        print("\n🚨 警告: 人間の評価値がどのフィールドにも残っていません。上書きリセットされた可能性が高いです。")
    else:
        print("\n🎉 成功: 有効な評価データが残っているフィールドが見つかりました！")

if __name__ == '__main__':
    audit_firestore_full()

import random
import firebase_admin
from firebase_admin import firestore

print("🔥 過去データへの『random_weight』マイグレーションを開始します...")

if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.client()
docs = db.collection('nazokake_items').stream()

batch = db.batch()
count = 0
total = 0

for doc in docs:
    data = doc.to_dict()
    if 'random_weight' not in data:
        batch.update(doc.reference, {'random_weight': random.random()})
        count += 1
        total += 1
        if count == 400:
            batch.commit()
            print(f"✅ {total} 件のドキュメントにランダムシードを付与しました...")
            batch = db.batch()
            count = 0

if count > 0:
    batch.commit()
    print(f"✅ 残り {count} 件をコミットしました。")

if total == 0:
    print("✨ すべてのデータは既にアップデート済みです！")
else:
    print(f"🎉 マイグレーション完了！ 合計 {total} 件の過去データが救済されました！")
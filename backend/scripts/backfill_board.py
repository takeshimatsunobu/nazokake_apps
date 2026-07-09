import firebase_admin
from firebase_admin import firestore

print("=========================================")
print("🚀 掲示板過去データ カテゴリ一括付与（バックフィル） [最終防弾版]")
print("=========================================")


def main():
    PROJECT_ID = "nazokakeapp-137e5"

    # 鍵ファイルを探さず、明示的にプロジェクトIDを指定してADC（gcloud認証）で突破する
    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})

    db = firestore.client()
    count = 0
    total_updated = 0

    batch = db.batch()
    docs = db.collection("board_posts").stream()

    print("⏳ データを走査中...")
    for doc in docs:
        d = doc.to_dict() or {}
        if "category" not in d:
            batch.update(doc.reference, {"category": "nazokake"})
            count += 1
            total_updated += 1

            if count >= 500:
                batch.commit()
                print(f"  ... {total_updated}件更新完了")
                count = 0
                batch = db.batch()

    if count > 0:
        batch.commit()
        print(f"  ... {total_updated}件更新完了")

    print(
        f"\n🎉 バックフィル完了！ 合計 {total_updated} 件のデータにカテゴリを付与しました。"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"🚨 エラー発生: {e}")

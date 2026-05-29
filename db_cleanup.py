import os
from google.cloud import firestore

def print_header(title):
    print("\n" + "="*60)
    print(f" 🧹 {title}")
    print("="*60)

def main():
    print_header("Firestore データクレンジング（大掃除）プログラム v2")
    print("データベースをスキャンし、グラフ描画を壊す原因となる「不良データ」を特定します...\n")
    
    try:
        db = firestore.Client()
        docs = db.collection("nazokake_items").stream()
        
        bad_docs = []
        
        for doc in docs:
            data = doc.to_dict()
            status = data.get("status")
            scores = data.get("scores", {})
            
            is_bad = False
            reason = ""
            
            # 判定ロジック
            if status == 9:
                is_bad = True
                reason = "過去の処理エラー放置 (status: 9)"
            elif status == 2:
                if not scores:
                    is_bad = True
                    reason = "評価完了(2)なのに scores が空っぽ"
                # 💡 追加：scoresが辞書(dict)型じゃない（リスト等になっている）場合は不良データ！
                elif not isinstance(scores, dict):
                    is_bad = True
                    reason = f"scores のデータ型が異常です (辞書ではなく {type(scores).__name__} になっています)"
                elif len(scores) < 11:
                    is_bad = True
                    reason = f"評価軸の欠損 (現在 {len(scores)}個しかありません)"
                else:
                    # 型チェック（文字列が混入していないか）
                    for k, v in scores.items():
                        if type(v).__name__ == "str":
                            is_bad = True
                            reason = f"スコアに文字列が混入 ('{k}': '{v}')"
                            break
            
            # 開発初期のstatusなし等の異常なデータも掃除
            elif status not in [0, 1, 2, 9, -9]:
                is_bad = True
                reason = f"不明なステータス ({status})"

            if is_bad:
                bad_docs.append({
                    "id": doc.id, 
                    "reason": reason, 
                    "title": data.get("A_TITLE", "無題")
                })
                
        if not bad_docs:
            print("✨ 素晴らしい！データベースに不良データは見つかりませんでした。完全にクリーンです！")
            return
            
        print(f"⚠️ {len(bad_docs)} 件の不良データが見つかりました。\n")
        for i, bad in enumerate(bad_docs[:15]):
            print(f"  - ID: {bad['id']} | お題: {bad['title']} \n    理由: {bad['reason']}")
            
        if len(bad_docs) > 15:
            print(f"  ... 他 {len(bad_docs) - 15} 件")
            
        print("\n" + "-"*60)
        ans = input(f"❓ これら {len(bad_docs)} 件の不良データをデータベースから【完全に削除】しますか？ (y/n) > ")
        
        if ans.lower() == 'y':
            print("\n🗑️ 削除を開始します...")
            batch = db.batch()
            count = 0
            for bad in bad_docs:
                doc_ref = db.collection("nazokake_items").document(bad['id'])
                batch.delete(doc_ref)
                count += 1
                # Firestoreのバッチ制限(500件)への対応
                if count % 500 == 0:
                    batch.commit()
                    batch = db.batch()
            
            if count % 500 != 0:
                batch.commit()
                
            print(f"✅ {count} 件のデータを綺麗に削除しました！データベースはピカピカです。")
        else:
            print("🛑 削除をキャンセルしました。")

    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")

if __name__ == "__main__":
    main()

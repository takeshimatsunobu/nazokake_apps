from google.cloud import firestore

db = firestore.Client()

def audit_training_data():
    print("📊 [Data Audit] Firestoreの学習用データの在庫を確認中...\n")
    try:
        # プロジェクトの歴史上使われてきた2つのコレクションを両方チェック
        collections = ["nazokake_items", "nazokake_evaluations"]
        
        for col_name in collections:
            # status が 2 (評価完了) のドキュメントを取得
            query = db.collection(col_name).where("status", "==", 2)
            docs = list(query.stream())
            count_total = len(docs)
            
            if count_total == 0:
                continue
                
            print(f"📁 コレクション: {col_name}")
            print(f"  ✅ 評価完了データ (status=2) 総数: {count_total} 件")
            
            # RLHF (人間の評価) が付与されているかチェック
            human_evals = sum(1 for d in docs if d.to_dict().get("FINAL_SCORE_HUMAN") is not None)
            print(f"  👨‍⚖️ うち、人間の評価(RLHF)あり: {human_evals} 件\n")
            
    except Exception as e:
        print(f"🚨 データベーススキャン中にエラーが発生しました: {e}")

if __name__ == "__main__":
    audit_training_data()

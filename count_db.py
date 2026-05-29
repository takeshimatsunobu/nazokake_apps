import os
from google.cloud import firestore

def print_header(title):
    print("\n" + "="*60)
    print(f" 📊 {title}")
    print("="*60)

def main():
    print_header("Firestore 真のデータ件数カウント")
    print("データベースをスキャンし、正確なドキュメント数を集計しています...\n")
    
    try:
        db = firestore.Client()
        docs = db.collection("nazokake_items").stream()
        
        total_count = 0
        status_counts = {}
        
        for doc in docs:
            total_count += 1
            data = doc.to_dict()
            status = data.get("status", "不明")
            
            # ステータスごとにカウント
            if status in status_counts:
                status_counts[status] += 1
            else:
                status_counts[status] = 1
                
        print(f"✨ データベース内の【真の全データ件数】: {total_count} 件")
        print("-" * 60)
        print("【ステータス別の内訳】")
        for s, count in sorted(status_counts.items(), key=lambda x: str(x[0])):
            if s == 2:
                print(f"  🟢 評価完了 (status: 2) : {count} 件")
            elif s == 1:
                print(f"  🟡 処理中 (status: 1)   : {count} 件")
            elif s == 0:
                print(f"  ⚪ 未処理 (status: 0)   : {count} 件")
            elif s == 9:
                print(f"  🔴 エラー (status: 9)   : {count} 件")
            elif s == -9:
                print(f"  🗑️ スパム (status: -9)  : {count} 件")
            else:
                print(f"  ❓ その他 (status: {s}) : {count} 件")
                
        print("-" * 60)
        print("💡 もしこの合計件数が想定通り（約5000〜6000件）であれば、")
        print("   先ほどの9300件は単なる『二重カウント表示』だったことが証明されます！")

    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")

if __name__ == "__main__":
    main()

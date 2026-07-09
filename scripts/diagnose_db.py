import firebase_admin
from firebase_admin import firestore
from collections import Counter
import traceback

def diagnose_database():
    print("\n================ [ ファクト確認: Firestore 全件 構造診断 ] ================")
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        db = firestore.client()
        
        print("⏳ データベース全体を高速スキャン中... (数秒〜数十秒お待ちください)")
        
        # 通信量を極限まで減らすため、'status' と 'timestamp' のキーだけをピンポイントで抽出
        docs = db.collection("nazokake_items").select(['status', 'timestamp']).stream()
        
        total_count = 0
        status_counter = Counter()
        missing_timestamp_count = 0
        status_2_missing_ts = 0
        
        for doc in docs:
            total_count += 1
            data = doc.to_dict()
            
            # 1. ステータスの集計
            status = data.get('status', 'MISSING (キーなし)')
            status_counter[str(status)] += 1
            
            # 2. timestamp欠損の集計
            if 'timestamp' not in data:
                missing_timestamp_count += 1
                if status == 2 or status == '2':
                    status_2_missing_ts += 1

        print(f"\n📊 【診断結果】")
        print(f"総ドキュメント数: {total_count} 件")
        
        print("\n📈 ステータス別の内訳:")
        # 件数が多い順に並び替えて表示
        for stat, count in status_counter.most_common():
            print(f"  - status: {stat} -> {count} 件")
            
        print("\n⚠️ 隠れたリスク (サイレント・ドロップの確認):")
        print(f"  - timestampが存在しないデータ総数: {missing_timestamp_count} 件")
        print(f"  - (うち、status: 2 なのに欠損しているため除外されたデータ: {status_2_missing_ts} 件)")
        
        print("\n💡 結論:")
        if status_2_missing_ts > 0:
            print(f"  Firestoreの仕様により、{status_2_missing_ts}件の status:2 データが暗黙的に除外されていました！")
        else:
            print("  暗黙の除外はありません。抽出件数の違いは、単に他のステータスが存在するためです。")

    except Exception as e:
        print(f"🚨 診断中にエラーが発生しました:")
        traceback.print_exc()

if __name__ == "__main__":
    diagnose_database()

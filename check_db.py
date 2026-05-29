import os
from google.cloud import firestore

def print_header(title):
    print("\n" + "="*60)
    print(f" 🕵️ {title}")
    print("="*60)

print_header("Firestore データ構造 徹底調査 (0.0バグ & 型チェック)")

try:
    db = firestore.Client()
    # 最新の「評価完了(status: 2)」データを直近3件取得して比較
    docs = db.collection("nazokake_items")\
             .where(filter=firestore.FieldFilter("status", "==", 2))\
             .order_by("created_at", direction=firestore.Query.DESCENDING)\
             .limit(3).stream()

    found = False
    for doc in docs:
        found = True
        data = doc.to_dict()
        print(f"\n✅ 対象ドキュメントID: {doc.id}")
        print(f"📝 お題: {data.get('A_TITLE', '不明')}")
        print(f"🗣️ 本文: {data.get('nazokake_text', '不明')[:30]}...")
        print("-" * 60)
        
        scores = data.get("scores")
        
        if not scores:
            print("❌ 【原因確定】: 'scores' という項目がデータベースに存在しません！")
            continue
            
        print("📊 'scores' の中身とデータ型:")
        is_string_bug = False
        is_all_zero = True
        
        for key, value in scores.items():
            val_type = type(value).__name__
            print(f"  - {key}: {value} (型: {val_type})")
            if val_type == "str":
                is_string_bug = True
            # float変換可能かチェックし、0.0より大きい値があるか確認
            try:
                if float(value) > 0.0:
                    is_all_zero = False
            except:
                pass
        
        print("-" * 60)
        print(f"👉 記録されている評価軸の数: {len(scores)} 個")
        
        if len(scores) < 11:
            print("❌ 【原因確定】: 軸の数が11個揃っていません（データの歯抜けバグです）")
        elif is_string_bug:
            print("❌ 【原因確定】: スコアが数値(float)ではなく、文字列(str)として保存されています！(グラフが真っ白になる原因)")
        elif is_all_zero:
            print("❌ 【原因確定】: すべてのスコアが 0.0 です！(バックエンドのJSONパース失敗によるフォールバックの可能性大)")
        else:
            print("✨ 【診断結果】: データベース上の 'scores' は完璧な数値型で揃っています！(フロント側の描画ロジックの問題です)")

    if not found:
        print("⚠️ status: 2 のデータが1件も見つかりませんでした。")

except Exception as e:
    print(f"❌ エラーが発生しました: {e}")

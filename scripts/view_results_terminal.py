import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path

def print_terminal_dashboard():
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("=" * 60)
    print("🏆 ターミナル版・なぞかけ鑑定結果ダッシュボード 🏆")
    print("=" * 60)
    
    try:
        docs = db.collection("nazokake_items").where("author", "==", "Takeshi_Gemini_Brainstorm").stream()
        
        found = False
        for doc in docs:
            found = True
            data = doc.to_dict()
            
            title = data.get("A_TITLE", "不明")
            text = data.get("nazokake_text", "不明")
            status = data.get("status", "不明")
            scores = data.get("scores", {})
            reasoning = data.get("reasoning", "講評がまだありません（またはエラー）")
            
            print(f"\n✨ お題: 【 {title} 】")
            print(f"📝 本文: {text}")
            print(f"🔄 内部ステータス: {status}")
            
            if scores:
                print("\n📊 --- AI 11軸レーダー評価 ---")
                total_score = 0
                for axis, score in scores.items():
                    print(f"   - {axis:<15}: {score:.2f} / 1.0")
                    total_score += score
                # 5点満点に換算（11軸の平均 × 5）
                avg_5_scale = (total_score / 11) * 5
                print(f"🌟 総合換算スコア: {avg_5_scale:.2f} / 5.00")
                
                print("\n🗣️ --- AI審査員の講評 ---")
                # 長い講評を見やすく改行
                print(reasoning)
            else:
                print("\n⚠️ AIの評価データ（scores）がまだ書き込まれていません。")
                print("   (裏側でGeminiが推論中か、エラーで停止した可能性があります)")
                
            print("\n" + "=" * 60)
            
        if not found:
            print("⚠️ 該当するデータが見つかりません。")
            
    except Exception as e:
        print(f"🚨 エラー発生: {e}")

if __name__ == "__main__":
    print_terminal_dashboard()

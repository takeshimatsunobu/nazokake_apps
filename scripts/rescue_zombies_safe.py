import sys
import asyncio
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

sys.path.append(str(Path.cwd() / "backend"))
from services.evaluation import run_evaluation

async def process_zombies():
    load_dotenv()
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 データベースからデータを一括でメモリに読み込みます（タイムアウト対策）...")
    
    # 同期I/Oブロッキングを防ぐため to_thread で実行
    all_docs = await asyncio.to_thread(lambda: list(db.collection("nazokake_items").stream()))
    
    zombies = []
    for doc in all_docs:
        data = doc.to_dict()
        status = data.get("status", 0)
        eval_status = data.get("eval_status", "")
        
        # 完了(2, "completed") または エラー(-1, "error") 以外の「鑑定中」を抽出
        if status not in [2, "completed", -1, "error"] and eval_status not in ["completed", "error"]:
            zombies.append((doc.id, data.get("A_TITLE", "不明"), data.get("nazokake_text", "")))
    
    if not zombies:
        print("\n✨ 素晴らしい！『鑑定中』で止まっているゾンビデータは1件もありませんでした。")
        return

    print(f"\n🧟 {len(zombies)}件のゾンビデータを発見。順次救出を開始します...")
    
    count = 0
    for doc_id, title, text in zombies:
        print(f"\n🚀 AI評価エンジン起動: お題「{title}」")
        doc_ref = db.collection("nazokake_items").document(doc_id)
        try:
            # run_evaluation は評価結果を返すのみ(DB更新は行わない)ため、
            # submission.py / generate.py と同じパターンでここに書き込み責務を持たせる。
            ev = await run_evaluation(title, text)
            await asyncio.to_thread(doc_ref.update, {
                "scores": ev["scores"], "s_total": ev["s_total"],
                "axis_comments": ev["axis_comments"], "overall": ev["overall"],
                "eval_status": "completed", "feed_ready": True, "status": "all_completed",
            })
            count += 1
            print(f"✅ 「{title}」の評価・保存処理が完了しました！")
        except Exception as e:
            # 失敗してもゾンビ状態(鑑定中)に戻さず error に確定させ、無限ロードを防ぐ。
            await asyncio.to_thread(doc_ref.update, {
                "status": "error", "eval_status": "error", "message": f"評価に失敗しました: {e}",
            })
            print(f"🚨 救出失敗 「{title}」: {e}")

    print(f"\n🎉 計 {count} 件のゾンビデータの評価・救出が完了しました！")

def rescue_zombies_safe():
    asyncio.run(process_zombies())

if __name__ == "__main__":
    rescue_zombies_safe()

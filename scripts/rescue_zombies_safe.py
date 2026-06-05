import sys
import asyncio
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

sys.path.append(str(Path.cwd() / "backend"))
from services.ai_service import evaluate_and_update_task

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
        try:
            # Phase 1 で非同期化(async def)された関数を正しく await する
            await evaluate_and_update_task(db, doc_id, title, text)
            count += 1
            print(f"✅ 「{title}」の評価・保存処理が完了しました！")
        except Exception as e:
            print(f"🚨 救出失敗 「{title}」: {e}")

    print(f"\n🎉 計 {count} 件のゾンビデータの評価・救出が完了しました！")

def rescue_zombies_safe():
    asyncio.run(process_zombies())

if __name__ == "__main__":
    rescue_zombies_safe()

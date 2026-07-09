import asyncio
import os
import sys
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# backendフォルダ内のモジュールを読み込めるようにパスを追加
sys.path.append(str(Path.cwd() / "backend"))
from services.evaluation import run_evaluation

async def run_local_evaluation():
    load_dotenv() # 環境変数（APIキー等）の読み込み
    
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    
    # 🚨 修正ポイント: 以前成功した「安全な認証フォールバック」を追加
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 未評価 (status: 0) の注入作品を捜索中...")
    try:
        docs = db.collection("nazokake_items").where("author", "==", "Takeshi_Gemini_Brainstorm").stream()
        
        found = False
        for doc in docs:
            data = doc.to_dict()
            if data.get("status") != 0:
                continue
                
            found = True
            doc_id = doc.id
            title = data.get("A_TITLE", "不明")
            text = data.get("nazokake_text", "")

            print(f"\n🚀 お題: {title} の評価エンジンをローカルで直接起動します！")

            # run_evaluation は評価結果を返すのみ(DB更新は行わない)ため、
            # submission.py / generate.py と同じパターンでここに書き込み責務を持たせる。
            doc_ref = db.collection("nazokake_items").document(doc_id)
            try:
                ev = await run_evaluation(title, text)
                await asyncio.to_thread(doc_ref.update, {
                    "scores": ev["scores"], "s_total": ev["s_total"],
                    "axis_comments": ev["axis_comments"], "overall": ev["overall"],
                    "eval_status": "completed", "feed_ready": True, "status": "all_completed",
                })
                print(f"✅ {title} の評価・保存が完了しました！")
            except Exception as e:
                await asyncio.to_thread(doc_ref.update, {
                    "status": "error", "eval_status": "error", "message": f"評価に失敗しました: {e}",
                })
                print(f"🚨 {title} の評価に失敗しました: {e}")

        if not found:
            print("⚠️ 未評価のデータは見つかりませんでした。")

    except Exception as e:
        print(f"🚨 エラー発生: {e}")

if __name__ == "__main__":
    asyncio.run(run_local_evaluation())

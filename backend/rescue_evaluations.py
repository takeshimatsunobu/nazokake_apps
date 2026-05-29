import os
import sys
import importlib.util
import inspect
import glob
import asyncio
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# 1. 魔法のおまじない：現在のフォルダ全体をPythonに認識させる
sys.path.insert(0, os.getcwd())

# Firebase初期化
key_files = glob.glob("*firebase-adminsdk*.json") + glob.glob("../*firebase-adminsdk*.json")
if not key_files:
    print("🚨 JSON鍵ファイルが見つかりません。")
    sys.exit()

if not firebase_admin._apps:
    cred = credentials.Certificate(key_files[0])
    firebase_admin.initialize_app(cred)

db = firestore.client()
collection_name = "nazokake_items"

# 2. ファイル名に頼らず、コードの中身から「評価プログラム」を探し出す！
eval_file = None
for root, dirs, files in os.walk("."):
    if ".venv" in root or "__pycache__" in root: continue
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    # 評価用のキーワードが含まれているファイルを特定
                    if "S_sur" in content and "def " in content:
                        eval_file = path
                        break
            except: pass
    if eval_file: break

if not eval_file:
    print("🚨 エラー: AI評価ロジックを含むファイルが見つかりません。")
    sys.exit()

print(f"🎯 評価ファイルを発見しました: {eval_file}")

# 3. 発見したファイルを強制的に読み込む
sys.path.insert(0, os.path.dirname(os.path.abspath(eval_file)))
module_name = os.path.basename(eval_file)[:-3]
spec = importlib.util.spec_from_file_location(module_name, eval_file)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# 4. その中から「評価を実行する関数」を自動特定する
eval_func = None
for name, obj in inspect.getmembers(mod, inspect.isfunction):
    if "eval" in name.lower() or "score" in name.lower() or "task" in name.lower() or "gemini" in name.lower():
        sig = inspect.signature(obj)
        if len(sig.parameters) >= 2:
            eval_func = obj
            break

if not eval_func:
    for name, obj in inspect.getmembers(mod, inspect.isfunction):
        if len(inspect.signature(obj).parameters) >= 2:
            eval_func = obj
            break

if not eval_func:
    print("🚨 エラー: 評価関数が見つかりません。")
    sys.exit()

print(f"🎯 評価関数を発見しました: {eval_func.__name__} (引数: {len(inspect.signature(eval_func).parameters)}個)")

# 5. 評価待ちのデータを全て呼び起こして救済する
async def process_docs():
    print("\n🔍 評価待ち（processing）のデータを検索中...")
    docs = db.collection(collection_name).where(filter=FieldFilter("eval_status", "==", "processing")).stream()
    
    rescue_count = 0
    for doc in docs:
        data = doc.to_dict()
        odai = data.get("A_TITLE", "不明")
        text = data.get("nazokake_text", "")
        
        print(f"🔄 救済中（再評価）: 【{odai}】...")
        try:
            sig = inspect.signature(eval_func)
            args_len = len(sig.parameters)
            is_coro = asyncio.iscoroutinefunction(eval_func)
            
            # 関数の形に合わせて柔軟に実行
            if args_len >= 3:
                result = await eval_func(doc.id, odai, text) if is_coro else eval_func(doc.id, odai, text)
            else:
                result = await eval_func(odai, text) if is_coro else eval_func(odai, text)
                    
            # データベースを更新
            if isinstance(result, dict) and "scores" in result:
                db.collection(collection_name).document(doc.id).update({
                    "scores": result["scores"],
                    "s_total": result.get("s_total", 0),
                    "eval_reasoning": result.get("reasoning", ""),
                    "reasoning": result.get("reasoning", ""),
                    "eval_status": "completed",
                    "status": "completed",
                    "evaluated_at": firestore.SERVER_TIMESTAMP
                })
            
            print(f"  └ ✅ 処理完了！")
            rescue_count += 1
        except Exception as e:
            print(f"  └ ❌ エラー: {e}")
            
    print(f"\n🎉 処理完了！ 合計 {rescue_count} 件のなぞかけを救済しました！")

# 実行
asyncio.run(process_docs())

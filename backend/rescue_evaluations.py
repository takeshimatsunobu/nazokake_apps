import os
import sys
import importlib.util
import inspect
import glob
import asyncio
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# --- Setup and Initialization ---

# 1. Path setup (Necessary for dynamic module loading)
sys.path.insert(0, os.getcwd())

# 2. Firebase Initialization
key_files = glob.glob("*firebase-adminsdk*.json") + glob.glob("../*firebase-adminsdk*.json")
if not key_files:
    print("🚨 JSON鍵ファイルが見つかりません。")
    sys.exit(1)

if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(key_files[0])
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"🚨 Firebase初期化エラー: {e}")
        sys.exit(1)

db = firestore.client()
collection_name = "nazokake_items"

# 3. Locate Evaluation Module
eval_file = None
for root, _, files in os.walk("."):
    if ".venv" in root or "__pycache__" in root:
        continue
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
            except Exception:
                continue
    if eval_file:
        break

if not eval_file:
    print("🚨 エラー: AI評価ロジックを含むファイルが見つかりません。")
    sys.exit(1)

print(f"🎯 評価ファイルを発見しました: {eval_file}")

# 4. Load Module Dynamically
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(eval_file)))
    module_name = os.path.basename(eval_file)[:-3]
    spec = importlib.util.spec_from_file_location(module_name, eval_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
except Exception as e:
    print(f"🚨 モジュールロードエラー: {e}")
    sys.exit(1)

# 5. Identify Evaluation Function
eval_func = None
for name, obj in inspect.getmembers(mod, inspect.isfunction):
    # 優先度の高いキーワードで検索
    if "eval" in name.lower() or "score" in name.lower() or "task" in name.lower() or "gemini" in name.lower():
        sig = inspect.signature(obj)
        # 引数が2つ以上ある関数を候補とする
        if len(sig.parameters) >= 2:
            eval_func = obj
            break

if not eval_func:
    # フォールバック: 引数が2つ以上ある最初の関数を採用
    for name, obj in inspect.getmembers(mod, inspect.isfunction):
        if len(inspect.signature(obj).parameters) >= 2:
            eval_func = obj
            break

if not eval_func:
    print("🚨 エラー: 評価関数が見つかりません。")
    sys.exit(1)

print(f"🎯 評価関数を発見しました: {eval_func.__name__} (引数: {len(inspect.signature(eval_func).parameters)}個)")

# --- Main Processing Logic ---

async def process_docs():
    """
    評価待ちのFirestoreドキュメントを検索し、評価関数を実行して結果を更新する。
    """
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
            
            result = None
            
            # 実行する引数を決定
            if args_len >= 3:
                args = (doc.id, odai, text)
            else:
                args = (odai, text)
            
            # 関数を実行 (async/sync対応)
            if is_coro:
                result = await eval_func(*args)
            else:
                result = eval_func(*args)
                    
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
if __name__ == "__main__":
    asyncio.run(process_docs())
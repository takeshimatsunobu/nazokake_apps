import os
from collections import Counter
import firebase_admin
from firebase_admin import firestore

def scan_codebase():
    target_exts = {'.py', '.js', '.html'}
    exclude_dirs = {'.venv', '.venv_ai', '__pycache__', '.git', 'node_modules', '.agents', '.vscode'}
    
    file_count = 0
    total_lines = 0
    
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for file in files:
            if any(file.endswith(ext) for ext in target_exts):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        total_lines += len(lines)
                        file_count += 1
                except Exception:
                    pass
    return file_count, total_lines

def check_firestore_status():
    if not firebase_admin._apps:
        # デフォルト認証（ADC）への安全なフォールバック
        firebase_admin.initialize_app()
    
    db = firestore.client()
    try:
        docs = db.collection("nazokake_items").select(["status"]).stream()
        status_counter = Counter()
        for doc in docs:
            data = doc.to_dict()
            status = data.get("status", "Missing")
            # 型チェック（文字列型として混入しているゾンビデータを炙り出す）
            status_type = type(status).__name__
            status_counter[f"{status} (Type: {status_type})"] += 1
            
        return status_counter
    except Exception as e:
        return f"Firestore Error: {e}"

if __name__ == "__main__":
    print("🔍 [Phase 1] コードベースのAST解析前ベースラインを計測中...")
    files, lines = scan_codebase()
    print(f"   => 対象ファイル数: {files} / 総行数: {lines} 行")
    
    print("\n📊 [Phase 2] Firestoreデータのクレンジング前ベースラインを監査中...")
    status_counts = check_firestore_status()
    if isinstance(status_counts, Counter):
        for stat, count in status_counts.items():
            print(f"   => Status: {stat} : {count} 件")
    else:
        print(status_counts)
    print("\n✅ 計測完了。")

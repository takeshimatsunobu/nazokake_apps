import re

main_path = 'backend/main.py'
try:
    with open(main_path, 'r', encoding='utf-8') as f:
        code = f.read()

    # 必要なインポートの追加
    if 'from fastapi.security import HTTPBasic' not in code:
        imports_to_add = '''import secrets
from fastapi import Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    current_user_bytes = credentials.username.encode("utf8")
    correct_user_bytes = os.environ.get("ADMIN_USER", "takeshi").encode("utf8")
    is_correct_user = secrets.compare_digest(current_user_bytes, correct_user_bytes)
    
    current_pass_bytes = credentials.password.encode("utf8")
    correct_pass_bytes = os.environ.get("ADMIN_PASS", "nazo_master999").encode("utf8")
    is_correct_pass = secrets.compare_digest(current_pass_bytes, correct_pass_bytes)
    
    if not (is_correct_user and is_correct_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
'''
        # typingインポートの下あたりに挿入
        code = code.replace('from typing import Optional', 'from typing import Optional\n' + imports_to_add)

    # 各エンドポイントへのプロテクト追加
    code = code.replace('@app.post("/api/admin/toggle_golden")', '@app.post("/api/admin/toggle_golden", dependencies=[Depends(verify_admin)])')
    code = code.replace('@app.post("/api/admin/delete")', '@app.post("/api/admin/delete", dependencies=[Depends(verify_admin)])')
    code = code.replace('@app.get("/admin")', '@app.get("/admin", dependencies=[Depends(verify_admin)])')

    with open(main_path, 'w', encoding='utf-8') as f:
        f.write(code)
    print("✅ main.py の管理者APIと画面に鍵（Basic認証）をかけました！")

except Exception as e:
    print(f"🚨 エラーが発生しました: {e}")

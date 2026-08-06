import pathlib
p = pathlib.Path("apps/evaluator/backend/api/routers/admin.py")
if p.exists():
    lines = p.read_text(encoding="utf-8").splitlines()
    # ローカルインポート文のみを除外
    new_lines = [line for line in lines if "from fastapi import HTTPException" not in line]
    p.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

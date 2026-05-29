import re

main_path = 'backend/main.py'
try:
    with open(main_path, 'r', encoding='utf-8') as f:
        code = f.read()

    # 既に注入済みでなければ追加する
    if '/api/admin/delete' not in code:
        admin_api_code = '''
# === 管理者用API ===
class AdminToggleRequest(BaseModel):
    doc_id: str
    is_golden: bool

class AdminDeleteRequest(BaseModel):
    doc_id: str

@app.post("/api/admin/toggle_golden")
async def admin_toggle_golden(req: AdminToggleRequest):
    try:
        doc_ref = db.collection("nazokake_items").document(req.doc_id)
        # 現在のis_goldenを反転させる
        doc_ref.update({"is_golden": not req.is_golden})
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/delete")
async def admin_delete(req: AdminDeleteRequest):
    try:
        db.collection("nazokake_items").document(req.doc_id).delete()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
'''
        # フロントエンド配信設定ブロックの直前に挿入
        code = code.replace('# --- フロントエンド配信設定 ---', admin_api_code + '\n# --- フロントエンド配信設定 ---')
        
        with open(main_path, 'w', encoding='utf-8') as f:
            f.write(code)
        print('✅ main.py に管理者用API（削除・殿堂入り）を注入しました！')
    else:
        print('✅ 管理者用APIは既に main.py に存在しています。')
except Exception as e:
    print(f'🚨 エラーが発生しました: {e}')

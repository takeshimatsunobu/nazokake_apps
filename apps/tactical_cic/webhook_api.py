import os
import sqlite3
import uuid
import json
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from .mdmp_engine import analyze_target, run_mdmp_session, audit_warhead
from .migrate_db import migrate_schema
from api.deps import verify_admin_token

# instructions/236: このルーターは元々「webhook」を名乗るが、実際には外部サービス
# (GitHub等)からのサーバー間呼び出しではなく、/cicダッシュボード(人間の操作者)が
# ブラウザから直接叩く内部ツール(public/js/cic_app.js参照、外部からのWebhook送信元は
# 存在しない)。そのため、他のadmin系ルーターと同じFirebase Auth
# (verify_admin_token)で統一する。router全体にdependenciesを付けることで、
# 個々のエンドポイントへの付け忘れを構造的に防ぐ。
router = APIRouter(dependencies=[Depends(verify_admin_token)])

# DB接続ユーティリティ
# プロジェクトルート基準の絶対パスで解決する(相対パスのままだとuvicornの実行cwd
# (apps/evaluator/backend)から見て存在しない別ファイルを新規作成してしまい、
# migrate_db.pyで作成済みのtactical_missionsテーブルが見つからずOperationalErrorになる)。
#
# 【instructions/225フォローアップで判明】コンテナ内では/app(=_PROJECT_ROOT)が
# root:root・755で所有されており、非rootのappuserには書き込み権限が無いため、
# sqlite3.connect()が`unable to open database file`で即座にクラッシュする
# (実機Cloud Buildで確認済み)。/appの権限を緩めてまで書き込み先にする必要は無く、
# そもそもこのDBはCloud Runの各インスタンスが再起動のたびに失う前提の一時データ
# (instructions/225の考察: tactical_cicは未着手のプロトタイプ機能で永続化の
# 実装対象外)なので、Cloud Runでも書き込み保証のある/tmp(ephemeral、
# 全プロセスに書き込み権限あり)を素直に使う。PROJECT_ROOT環境変数はDockerfileが
# コンテナ内でのみ明示的に設定するため、これをコンテナ判定に流用する
# (main.pyの_PROJECT_ROOT解決と同じ考え方)。ローカル開発では従来通り
# リポジトリルート直下に置く。
if os.environ.get("PROJECT_ROOT"):
    _DB_DIR = Path("/tmp")
else:
    _DB_DIR = Path(__file__).resolve().parents[2]
_LOCAL_SSOT_DB = _DB_DIR / 'local_ssot.db'
_NAZOKAKE_DB = _DB_DIR / 'nazokake.db'
DB_PATH = str(_LOCAL_SSOT_DB if _LOCAL_SSOT_DB.exists() else _NAZOKAKE_DB)

# 【instructions/225: 起動時自動マイグレーション】このrouterはmain.py起動時に
# importされる(=コンテナ起動のたびに評価される)ため、ここでmigrate_schema()を
# 呼ぶことで、Cloud Runの新規インスタンス起動時にtactical_missionsテーブルが
# 存在しない状態を解消する。CREATE TABLE IF NOT EXISTSなので毎回呼んでも安全。
# 上記で解決したDB_PATH(このモジュール自身のパス計算)を明示的に渡すことで、
# migrate_db.py側の独立したパス計算と食い違う可能性を構造的に排除する
# (instructions/225で判明した2箇所のparents[N]不一致バグの再発防止)。
migrate_schema(DB_PATH)

def get_db():
    # check_same_thread=False: このジェネレータはFastAPIによりスレッドプール上で
    # 実行されるが、接続を使うasyncルート本体はイベントループのスレッドで動く
    # (=connect()した時のスレッドと実際に使うスレッドが異なる)。接続自体はリクエスト
    # ごとに新規生成しレスポンス後にcloseするため、スレッド間で共有され続けることはない。
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# リクエストスキーマ
class ShareRequest(BaseModel):
    url: str
    thread_text: Optional[str] = "ダミーの炎上スレッド本文（※実際はクローラー等で取得）"

class FireRequest(BaseModel):
    selected_warhead: str

@router.get('/health')
def health_check():
    return {'status': 'Tactical CIC is online.', 'anti_hubris_protocol': 'active'}

@router.post('/webhook/share')
async def receive_share(req: ShareRequest, db: sqlite3.Connection = Depends(get_db)):
    '''Phase 1 & 2: 標的捕捉と弾頭鋳造'''
    cursor = db.cursor()
    
    # 🚨 【Anti-Hubris ③: Rate Limiting】 交戦規定: 24時間に1回
    cursor.execute("SELECT created_at FROM tactical_missions WHERE target_url = ? ORDER BY created_at DESC LIMIT 1", (req.url,))
    row = cursor.fetchone()
    if row:
        # 簡易パース処理 (末尾のZやミリ秒を考慮)
        last_created_str = row['created_at'].split('.')[0].replace('Z', '')
        last_created = datetime.fromisoformat(last_created_str)
        if datetime.utcnow() - last_created < timedelta(hours=24):
            raise HTTPException(
                status_code=429, 
                detail="交戦規定違反: 同一戦域への介入は24時間に1回に制限されています。"
            )
            
    mission_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO tactical_missions (mission_id, target_url, status) VALUES (?, ?, ?)",
        (mission_id, req.url, 'forging')
    )
    db.commit()
    
    # 幕僚AIプロセス実行
    context = await analyze_target(req.url, req.thread_text)
    forging_result = await run_mdmp_session(context)
    
    cursor.execute(
        "UPDATE tactical_missions SET status = ?, conflict_context = ?, coa_options = ? WHERE mission_id = ?",
        ('ready', context.model_dump_json(), forging_result.model_dump_json(), mission_id)
    )
    db.commit()
    
    return {
        "mission_id": mission_id, 
        "status": "ready", 
        "context": context,
        "coas": forging_result.coas
    }

@router.post('/missions/{mission_id}/audit')
async def audit_mission(mission_id: str, req: FireRequest):
    '''Phase 3: コミッサールAIによる動機監査'''
    audit_res = await audit_warhead(req.selected_warhead)
    return audit_res

@router.post('/missions/{mission_id}/fire')
async def fire_mission(mission_id: str, req: FireRequest, db: sqlite3.Connection = Depends(get_db)):
    '''Phase 3: 射出記録とAnti-Hubris発動'''
    cursor = db.cursor()
    now_iso = datetime.utcnow().isoformat()
    cursor.execute(
        "UPDATE tactical_missions SET status = 'fired', selected_warhead = ?, fired_at = ? WHERE mission_id = ?",
        (req.selected_warhead, now_iso, mission_id)
    )
    db.commit()
    
    # 🚨 【Anti-Hubris ②: 動機監査UI連動】 嫌味なトースト通知用メッセージ
    return {
        "status": "fired",
        "message": "発射しました。これ以上の介入は自己顕示欲です。スベる覚悟はできていますね？", 
        "fired_at": now_iso
    }

@router.get('/missions/{mission_id}/bda')
async def get_bda(mission_id: str, db: sqlite3.Connection = Depends(get_db)):
    '''Phase 4: BDA (ドーパミン・デトックス制約付き)'''
    cursor = db.cursor()
    cursor.execute("SELECT fired_at, bda_metrics FROM tactical_missions WHERE mission_id = ?", (mission_id,))
    row = cursor.fetchone()
    
    if not row or not row['fired_at']:
        raise HTTPException(status_code=404, detail="Mission not found or not fired yet.")
        
    fired_at_str = row['fired_at'].split('.')[0].replace('Z', '')
    fired_at = datetime.fromisoformat(fired_at_str)
    
    # 🚨 【Anti-Hubris ④: ドーパミン・デトックス】 18時間マスキング
    if datetime.utcnow() - fired_at < timedelta(hours=18):
        return {
            "status": "masking", 
            "message": "BDAレポートは封印されています。射出から18時間が経過するまで、ドーパミン・デトックスを遂行してください。",
            "bda_metrics": None # APIレベルで強制遮断
        }
        
    bda_data = json.loads(row['bda_metrics']) if row['bda_metrics'] else {"武装解除指数": "計測中"}
    return {"status": "available", "bda_metrics": bda_data}

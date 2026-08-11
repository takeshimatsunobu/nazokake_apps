"""
main.py
=========
ペルソナ推定とルーティングシステム — FastAPI エントリポイント(骨組み)。

apps/evaluator/backend と同じDDD再編規約(api/routers, models, services)に
従う。起動時のカレントディレクトリは必ずこのファイルのあるディレクトリ
(apps/persona_router)であること(下記「起動」参照。api.*/models.*/services.*
はこのディレクトリを起点とした絶対importのため、cwdがズレるとModuleNotFoundError
になる)。

起動: (apps/persona_router で) uv run fastapi dev main.py --port 8080
"""
from __future__ import annotations

import os

# 【重要: importの順序を変えないこと】api.routers(→services.step1_estimation等
# →nazokake_core.env_config)を先にimportすることで、env_config側の自動.env
# 読み込み(モジュールimport時に1回だけ発火する副作用、リポジトリルートの.envを
# 読む)を先に完了させる。その"後"で load_persona_router_env() を呼ぶことで、
# override=Trueの後勝ち原則により、このアプリ固有の値(STEP1_MODEL/STEP2_MODEL/
# GCP_PROJECT_ID)が正しく優先される(env.pyのdocstring参照)。
from api.routers import corrections, generate, personas, timeline, unlock
from env import load_persona_router_env

load_persona_router_env()

import firebase_admin  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

# ローカル開発機ではGOOGLE_CLOUD_PROJECT等のADC自動解決が効かないことがあるため、
# workers/ondemand_elyza_worker.py と同じ理由でprojectIdを明示する
# (未設定時はfirebase_adminのデフォルト解決に委ねる)。
_project_id = os.environ.get("GCP_PROJECT_ID")
if not firebase_admin._apps:
    if _project_id:
        firebase_admin.initialize_app(options={"projectId": _project_id})
    else:
        firebase_admin.initialize_app()

# apps/evaluator/backend/main.pyと同じ理由(localhost/127.0.0.1はブラウザの
# Same-Origin Policy上は別オリジン扱いのため両方明記、フロントエンドはfrontend/
# dev_server.pyで別ポートから配信する前提)。allow_origins=["*"]にしない理由:
# このAPIはCookie/認証情報を一切使わない(匿名UUIDはリクエストボディに含めず、
# ブラウザのlocalStorageのみで完結させる設計。フロントエンド実装のファクト
# チェック回答を参照)ため実害はほぼ無いが、許可オリジンを明示するほうが将来
# 認証を足した際の事故を未然に防げるため、evaluator/backendの規約を踏襲する。
app = FastAPI(title="Nazokake Persona Router", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(generate.router, tags=["generate"])
app.include_router(personas.router, tags=["personas"])
app.include_router(timeline.router, tags=["timeline"])
app.include_router(unlock.router, tags=["unlock"])
app.include_router(corrections.router, tags=["corrections"])


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

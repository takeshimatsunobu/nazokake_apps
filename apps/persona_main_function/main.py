"""
main.py
=========
お題属性推定とルーティングシステム — FastAPI エントリポイント(骨組み)。

【命名の是正、persona_feature_plan_v3.md §0】このサービスは自らを「ペルソナ推定」
と名乗っていたが、Step1(services/step1_estimation.py)が推定しているのはお題の
言語的性質7属性(is_valid_input/domain_category/vocabulary_difficulty/
slang_level/wordplay_flexibility/topic_scale/is_seasonal)であり、ペルソナでも
ユーザー属性でもない。「narrator persona」(PERSONAS[1..10])はStep2の生成入力
として使われるのみで、Step1では推定されない。実装は変更せず名称のみ是正する。

apps/evaluator/backend と同じDDD再編規約(api/routers, models, services)に
従う。起動時のカレントディレクトリは必ずこのファイルのあるディレクトリ
(apps/persona_main_function)であること(下記「起動」参照。api.*/models.*/services.*
はこのディレクトリを起点とした絶対importのため、cwdがズレるとModuleNotFoundError
になる)。

起動: (apps/persona_main_function で) uv run fastapi dev main.py --port 8080
"""
from __future__ import annotations

import os
import sys

# 【persona_feature_plan_v3.md Phase6】Windowsの既定コンソールはcp932であり、
# print()で絵文字(⚠️等)を出力するとUnicodeEncodeErrorが発生する
# (apps/evaluator/backend/main.py・workers/ondemand_elyza_worker.pyと同じ対策。
# services/persona_draft.pyのフェイルセーフ用ログ出力で実際に踏んだため追加した)。
# どのimportよりも前、かつこのファイル自身のprint()が呼ばれるより前に適用する。
if sys.platform == "win32":
    import io

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")

# 【重要: importの順序を変えないこと】api.routers(→services.step1_estimation等
# →nazokake_core.env_config)を先にimportすることで、env_config側の自動.env
# 読み込み(モジュールimport時に1回だけ発火する副作用、リポジトリルートの.envを
# 読む)を先に完了させる。その"後"で load_persona_main_function_env() を呼ぶことで、
# override=Trueの後勝ち原則により、このアプリ固有の値(STEP1_MODEL/STEP2_MODEL/
# GCP_PROJECT_ID)が正しく優先される(env.pyのdocstring参照)。
from api.routers import generate, personas, timeline, unlock
from env import load_persona_main_function_env

load_persona_main_function_env()

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
app = FastAPI(title="Nazokake Persona Main Function", version="0.1.0")
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
# 【persona_feature_plan_v3.md Phase9クリーンアップ】赤ペン添削の書き込み口を
# evaluator backend側のPOST /feed/evaluate/{doc_id}(SQLite user_akapen系統)へ
# 一本化したため、このアプリ独自のPOST /v1/corrections(corrections.router、
# Firestore corrections系統)は廃止した。旧実装はgit履歴を参照。


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

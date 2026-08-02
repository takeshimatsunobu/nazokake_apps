from fastapi.staticfiles import StaticFiles

# V8.9 Final Test
import os
import sys
from pathlib import Path
from loguru import logger

# apps/evaluator は別リポジトリとしてcwd(apps/evaluator/backend)基準で動くため、
# ルート直下の apps.tactical_cic を import するにはプロジェクトルートを明示的に
# sys.pathへ追加する必要がある(未追加だと ModuleNotFoundError: No module named 'apps'
# で起動時に即クラッシュする)。
#
# 【instructions/224で判明】ローカル開発時はmain.pyがリポジトリの実際の階層
# (apps/evaluator/backend/main.py)に存在するため parents[3] がリポジトリルートに
# 一致するが、DockerイメージはCOPYでこの階層を平坦化して/app/main.pyへ配置する
# ため、parents[3] が存在せず IndexError で起動即クラッシュする(初回の実デプロイ
# 試行で発覚)。コンテナ内ではDockerfileが明示的にPROJECT_ROOT環境変数(/app)を
# 設定するため、それを優先し、未設定時(ローカル開発)のみ既存のparents[3]へ
# フォールバックする。
_env_project_root = os.environ.get("PROJECT_ROOT")
_PROJECT_ROOT = (
    Path(_env_project_root)
    if _env_project_root
    else Path(__file__).resolve().parents[3]
)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.logger import setup_cloud_logging

setup_cloud_logging()

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import firebase_admin

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 🌟 機能ごとに独立したルーターを api/routers から読み込む
from api.routers import (
    generate,
    submission,
    feed,
    metrics,
    feedback,
    admin,
    board,
    admin_costs,
    user_feedback,
    admin_feedbacks,
    research,
)

# 🌟 ロギング初期化設定
logger.remove()
if os.getenv("K_SERVICE"):
    logger.add(sys.stderr, serialize=True)
else:
    logger.add(
        sys.stderr,
        colorize=True,
        format="<green>{time}</green> <level>{message}</level>",
    )

app = FastAPI(title="なぞかけディスカバリー API")

# Tactical CIC UIマウント
# directory はプロジェクトルート基準の絶対パスで指定する(相対パス"public"だと
# uvicornの実行cwd(apps/evaluator/backend)基準で解決され、そこにはpublic/が存在
# しないため StaticFiles初期化時に RuntimeError で起動即クラッシュする)。
app.mount(
    "/cic",
    StaticFiles(directory=str(_PROJECT_ROOT / "public"), html=True),
    name="cic_ui",
)


# 🌟 グローバル例外ハンドラの登録（アプリの突然死を防ぐ最終防波堤）
from core.exceptions import global_exception_handler  # noqa: E402
from apps.tactical_cic.webhook_api import router as cic_router

app.add_exception_handler(Exception, global_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🌟 重複のない明確なルーティング設定（機能別ルーター）
app.include_router(generate.router, prefix="/api", tags=["Generate"])
app.include_router(submission.router, prefix="/api", tags=["Submission"])
app.include_router(feed.router, prefix="/api", tags=["Feed"])
app.include_router(metrics.router, prefix="/api", tags=["Metrics"])
app.include_router(feedback.router, prefix="/api", tags=["Feedback"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(admin_costs.router, prefix="/api/admin", tags=["AdminCosts"])
app.include_router(user_feedback.router, prefix="/api", tags=["UserFeedback"])
app.include_router(admin_feedbacks.router, prefix="/api/admin", tags=["AdminFeedbacks"])
app.include_router(board.router, prefix="/api/board", tags=["Board"])
app.include_router(research.router, prefix="/api", tags=["Research"])
app.include_router(cic_router, prefix="/api/cic", tags=["Tactical CIC"])


@app.get("/api/health")
async def health_check():
    """💡 0円コールドスタート対策用の超軽量ヘルスチェック（DBアクセスなし）"""
    return {"status": "ok"}


# instructions/232: Cloud Runの各インスタンスは永続ボリュームを持たず、コンテナ起動の
# たびにSQLiteファイルが空の状態から始まる(NAZOKAKE_DB_PATHを/tmpへ切り替えた
# Dockerfile側の修正と対になる)。テーブル作成(CREATE TABLE IF NOT EXISTS)を
# 呼び出す経路がこれまでアプリ内に存在しなかったため、起動時に明示的に実行する。
from nazokake_core.database import init_db  # noqa: E402

# instructions/240: instructions/239で確立したPush(Cloud Run→Firestore)と対になる
# Pull(Firestore→Cloud Run)方向。init_db()直後、空のテーブルへFirestoreの内容を
# 復元することで、Cloud Run再起動を跨いだデータの実効的な永続化サイクルを完成させる。
from nazokake_core.firestore_sync import async_restore_from_firestore  # noqa: E402


@app.on_event("startup")
async def _init_db_on_startup() -> None:
    await init_db()
    try:
        await async_restore_from_firestore()
    except Exception as e:
        # 【絶対制約】リストア失敗はアプリ全体の起動をクラッシュさせない
        # (Firestore側の一時的な障害等でCloud Runの起動自体が失敗するのは本末転倒)。
        # ログ出力のみに留め、ローカルDBは空のまま起動を継続する。
        logger.warning(
            f"⚠️ Firestoreからのリストアに失敗しました(起動は継続します): {e}"
        )


# 【instructions/204: フロントエンド一元配信】フロントエンドを別ポートで立ち上げる
# 運用はCORSエラー・トイルの温床としてSRE監査でRejectされた。バックエンド(FastAPI)
# 自身がフロントエンドの静的ファイルを直接配信する。
#
# 【Step2: ルーティング競合の確認】Starletteはルート/マウントを登録順に評価する。
# このマウントは include_router(85-96行目)・/api/health(99-102行目)・/cic(66-68行目)
# の「後」に登録するため、/api/*・/cic/*・/api/healthへのリクエストはそれぞれの
# 専用ルートが先に一致し、このStaticFilesマウントへは到達しない。
# 以前ここに存在した`@app.get("/")`(素朴なJSONメッセージを返すだけの動作確認用
# ルート)は、登録順で常にこの静的ファイルマウントより先に一致してしまい
# `index.html`の配信を妨げるため削除した(html=Trueにより"/"はindex.htmlへ
# フォールバックする、StaticFiles標準の挙動)。
#
# directoryはuvicornの実行cwd(apps/evaluator/backend)に依存しない絶対パスで指定する
# 必要があるため、既存の/cicマウント(66-68行目)と同じ_PROJECT_ROOT基準で解決する
# (pathlibによる決定論的解決、instructions/204 Step1要件)。
app.mount(
    "/",
    StaticFiles(
        directory=str(_PROJECT_ROOT / "apps" / "evaluator" / "frontend" / "public"),
        html=True,
    ),
    name="static",
)

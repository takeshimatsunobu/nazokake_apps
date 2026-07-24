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
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
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
    "/cic", StaticFiles(directory=str(_PROJECT_ROOT / "public"), html=True), name="cic_ui"
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
app.include_router(cic_router, prefix="/api/cic", tags=["Tactical CIC"])


@app.get("/api/health")
async def health_check():
    """💡 0円コールドスタート対策用の超軽量ヘルスチェック（DBアクセスなし）"""
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"message": "Backend is cleanly structured and running!"}

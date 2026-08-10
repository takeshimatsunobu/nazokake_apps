from fastapi.staticfiles import StaticFiles

# V8.9 Final Test
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware
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

# 🌟 機能ごとに独立したルーターを api/routers から読み込む
# コンテナ内(/app)ではapps/evaluator/backend配下がCOPYで平坦化され
# apps.evaluator.backend パッケージ自体が存在しないため(ModuleNotFoundError:
# No module named 'apps.evaluator.backend')、main.pyと同じディレクトリを起点
# とする相対パッケージ名で読み込む(ローカル実行時もuvicornのcwdがこの
# ディレクトリのためimportは変わらず解決できる)。
from api.routers import (
    admin,
    admin_costs,
    admin_feedbacks,
    board,
    feed,
    feedback,
    generate,
    metrics,
    research,
    submission,
    user_feedback,
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

from nazokake_core.database import Base, _engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: DBスキーマの初期化(旧 @app.on_event("startup") から移行)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # shutdown: 現時点でクリーンアップ処理は無し(将来ここに追加する)


app = FastAPI(title="なぞかけディスカバリー API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nazokakeapp-137e5.web.app",
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        # ローカル開発の実際のuvicorn起動先(run_api.ps1/start_dev.ps1)。"localhost"と
        # "127.0.0.1"はブラウザのSame-Origin Policy上は別オリジン扱いのため両方明示する
        # (config.jsのAPI_BASEは常に127.0.0.1:8000へ固定される一方、ページ自体を
        # localhost:8000で開いた場合はオリジンが食い違いCORSプリフライトが必要になる)。
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルーターの登録 (research ルーター含む)
try:
    app.include_router(research.router)
except ImportError:
    pass

# 静的ファイルの配信 (マウント設定)
from pathlib import Path
from pathlib import Path

_BASE_DIR = _PROJECT_ROOT
_CIC_PUBLIC = _BASE_DIR / "public"
_RESEARCH_PUBLIC = _PROJECT_ROOT / "apps" / "evaluator" / "frontend" / "public"

# [1] Tactical CIC UI (/cic)
if _CIC_PUBLIC.exists():
    # [SRE Muted (Route Shadowing Fix)] app.mount("/cic", StaticFiles(directory=str(_CIC_PUBLIC), html=True), name="cic_static")
    pass

# [2] なぞかけ研究所 UI (ルート /)
if _RESEARCH_PUBLIC.exists():
    # [SRE Muted (Route Shadowing Fix)] app.mount("/", StaticFiles(directory=str(_RESEARCH_PUBLIC), html=True), name="research_static")
    pass

# --- SSoT準拠: 動的パス解決とルーティングの絶対法則 ---
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _PROJECT_ROOT

FRONTEND_DIR = PROJECT_ROOT / "apps" / "evaluator" / "frontend" / "public"
LEGACY_DIR = PROJECT_ROOT / "public"
DATA_DIR = PROJECT_ROOT / "data" / "research"

# 1. APIルーターの登録（最優先）
app.include_router(research.router, prefix="/api/research", tags=["research"])

# ルート側は各ルーターの@router内パスに既に/generate, /metrics/log,
# /submit_human, /feedback, /feed/..., /nazokake/{doc_id}/feedback が含まれる
# ため、/apiのみを付与する
app.include_router(generate.router, prefix="/api", tags=["generate"])
app.include_router(metrics.router, prefix="/api", tags=["metrics"])
app.include_router(submission.router, prefix="/api", tags=["submission"])
app.include_router(feedback.router, prefix="/api", tags=["feedback"])
app.include_router(feed.router, prefix="/api", tags=["feed"])
app.include_router(user_feedback.router, prefix="/api", tags=["user_feedback"])

# board.pyは/items, /postのみのため/api/boardを付与
app.include_router(board.router, prefix="/api/board", tags=["board"])

# admin系(admin.py: /action, /dlq, /audit_logs, /deploy / admin_costs.py:
# /costs, /costs/dashboard / admin_feedbacks.py: /feedbacks, ...)は
# 既存フロントエンド(admin.js)が ${API_BASE}/admin/... で呼ぶ規約に合わせ
# /api/adminを付与する
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(admin_costs.router, prefix="/api/admin", tags=["admin"])
app.include_router(admin_feedbacks.router, prefix="/api/admin", tags=["admin"])

@app.get("/api/health")
def healthz():
    return {"ok": True}

# 2. 旧UIの静的ファイルマウント（特化パスを先に）
app.mount("/cic", StaticFiles(directory=str(LEGACY_DIR), html=True), name="legacy")

# 3. 新UIの静的ファイルマウント（キャッチオールは必ず最後）
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")





# force ci trigger 20260810091256

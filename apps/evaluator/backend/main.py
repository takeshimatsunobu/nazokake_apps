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

# 🌟 機能ごとに独立したルーターを api/routers から読み込む
from apps.evaluator.backend.api.routers import (
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

# ルーターの登録 (research ルーター含む)
try:
    app.include_router(research.router)
except ImportError:
    pass

# 静的ファイルの配信 (マウント設定)
from pathlib import Path
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
_CIC_PUBLIC = _BASE_DIR / "public"
_RESEARCH_PUBLIC = Path(__file__).resolve().parent.parent / "frontend" / "public"

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
PROJECT_ROOT = BACKEND_DIR.parents[2]

FRONTEND_DIR = BACKEND_DIR.parent / "frontend" / "public"
LEGACY_DIR = PROJECT_ROOT / "public"
DATA_DIR = PROJECT_ROOT / "data" / "research"

# 1. APIルーターの登録（最優先）
app.include_router(research.router, prefix="/api/research", tags=["research"])

@app.get("/healthz")
def healthz():
    return {"ok": True}

# 2. 旧UIの静的ファイルマウント（特化パスを先に）
app.mount("/cic", StaticFiles(directory=str(LEGACY_DIR), html=True), name="legacy")

# 3. 新UIの静的ファイルマウント（キャッチオールは必ず最後）
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")






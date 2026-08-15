from fastapi.staticfiles import StaticFiles

# V8.9 Final Test
import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    admin_auth,
    admin_config,
    admin_costs,
    admin_feedbacks,
    admin_health,
    admin_review,
    board,
    feed,
    feedback,
    generate,
    metrics,
    persona_generate,
    personas,
    research,
    submission,
    timeline,
    unlock,
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
from nazokake_core.firestore_sync import async_restore_from_firestore

# --- Phase5.5: Cloud Run起動時のFirestore復元(instructions/240で設計されていたが
# 未配線だった「記憶喪失バグ」の解消)状態管理 ---
# Cloud Runコンテナの/tmp SQLiteはコンテナ再起動のたびに空になるため、起動時に
# Firestoreから復元しないと過去のnazokake_itemsが実質消え去っていた。
# _firestore_restore_done: 復元試行が完了(成功/失敗いずれか)した時点でsetされる。
# 起動プローブ(/api/health)をブロックしないよう、lifespan startupではこの完了を
# awaitしない(下記lifespan参照)。
_firestore_restore_done = asyncio.Event()
_firestore_restore_status: dict = {"state": "pending", "error": None, "stats": None}

# 復元ゲートの対象外パス。/api/healthはCloud Runの起動プローブ/ヘルスチェックが
# 叩くため、復元中でも常に即応する必要がある(復元自体の進捗もここで確認できる
# よう_firestore_restore_statusを応答に含める、下記healthz参照)。
_RESTORE_GATE_EXEMPT_PATHS = {"/api/health"}


async def _run_firestore_restore_in_background() -> None:
    """Firestoreからのリストアをバックグラウンドで実行する(lifespan startupから
    awaitせずasyncio.create_task()で起動される)。

    件数次第で数秒〜数十秒かかり得るため、ここでawaitして起動をブロックすると
    Cloud Runの起動プローブがタイムアウトしかねない。代わりにサーバー自体は
    即座に受付可能にしつつ、完了(成功/失敗問わず)するまでの間は
    _firestore_restore_gate ミドルウェアが /api/* リクエストへ503(復元中)を
    返すことで、不完全なデータへ静かに誤応答することを防ぐ。
    """
    global _firestore_restore_status
    _firestore_restore_status = {"state": "in_progress", "error": None, "stats": None}
    try:
        stats = await async_restore_from_firestore()
        _firestore_restore_status = {"state": "completed", "error": None, "stats": stats}
        logger.info(f"✅ [起動時リストア] Firestoreからの復元が完了しました: {stats}")
    except Exception as e:
        # 【絶対制約】リストア失敗はサーバー起動そのものを失敗させない。復元は
        # あくまでバックアップからの補完であり、失敗してもsync_once()による
        # 通常の同期(ローカル→Firestore)は継続できるため致命的ではない。
        _firestore_restore_status = {"state": "failed", "error": str(e), "stats": None}
        logger.error(f"⚠️ [起動時リストア] Firestoreからの復元に失敗しました(空のDBのまま起動を継続します): {e}")
    finally:
        # 成功/失敗どちらでも、これ以上APIリクエストをブロックし続けない
        # (失敗時に永久に503を返し続けるとサービス全体が機能しなくなるため)。
        _firestore_restore_done.set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: DBスキーマの初期化(旧 @app.on_event("startup") から移行)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Firestoreからの復元は上記の理由でawaitせず、バックグラウンドタスクとして
    # 起動するのみに留める(サーバーは即座にリクエスト受付可能になる)。
    restore_task = asyncio.create_task(_run_firestore_restore_in_background())
    yield
    # shutdown: 復元タスクが残っていればキャンセルする(コンテナ終了時に
    # 「タスクが破棄されました」という警告ログが出るのを防ぐだけの後始末)。
    if not restore_task.done():
        restore_task.cancel()


app = FastAPI(title="なぞかけディスカバリー API", lifespan=lifespan)


@app.middleware("http")
async def _firestore_restore_gate(request, call_next):
    """Firestoreからの起動時復元が完了するまで、/api/* への呼び出しを503で
    ガードする(/api/healthは常に例外、Cloud Runの起動プローブ用)。

    復元未完了の状態で/api/pending等が不完全なローカルDBへそのまま問い合わせて
    「静かに間違った(空に近い)結果」を返すことを防ぐのが目的。復元は通常
    数秒〜長くても数十秒で終わるため、待たせるのではなく即座に503+Retry-After
    を返しクライアント側の再試行に委ねる設計とした(長時間のリクエスト保留は
    Cloud Run/ブラウザ双方のタイムアウトと相性が悪いため)。

    このミドルウェアはCORSMiddlewareより先(=内側)に登録することで、503応答にも
    CORSヘッダーが正しく付与されるようにする(登録順=ミドルウェアのネスト順、
    後から追加したものほど外側になるStarletteの挙動に合わせた配置)。
    """
    path = request.url.path
    if path in _RESTORE_GATE_EXEMPT_PATHS or not path.startswith("/api"):
        return await call_next(request)
    if not _firestore_restore_done.is_set():
        return JSONResponse(
            status_code=503,
            content={
                "status": "restoring",
                "message": "起動時のデータ復元処理中です。数秒後に再試行してください。",
            },
            headers={"Retry-After": "5"},
        )
    return await call_next(request)

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
        # admin.html(管理コクピット)をリポジトリ既定のdev_server.py(port 7300)以外の
        # 汎用静的サーバー(例: `npx serve`/`python -m http.server 3000`等、port 3000で
        # 提供するツール)経由でローカル確認する場合に使う。CORSMiddlewareは許可オリジンに
        # 完全一致(スキーム+ホスト+ポート)を要求するため、未列挙のオリジンからの
        # プリフライト(OPTIONS)は400で拒否される(今回の障害の直接原因)。
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        # 現行のCloud Runサービス(nazokake-api)自身のURL。config.jsのAPI_BASEを相対パス
        # "/api"化した(firebase.jsonのCloud Runリライトと合わせ、Firebase Hosting経由・
        # Cloud Run直アクセスのいずれも同一オリジンになるため、この一覧は本来この2URLに
        # 対して必須ではなくなった)が、直接APIを叩く外部ツール・移行期の動作確認用に
        # 防御的に明示しておく。Cloud Runは同一サービスに新旧2種類のURL形式
        # (ハッシュ形式/プロジェクト番号形式)を割り当てるため両方とも列挙する。
        "https://nazokake-api-r6jq2erkta-an.a.run.app",
        "https://nazokake-api-862686676938.asia-northeast1.run.app",
        # 【統合(案B)】apps/persona_main_function/main.pyが個別に許可していた
        # フロントエンド開発サーバー(frontend/dev_server.py既定ポート)のオリジンを
        # マージする。単一Cloud Runサービスへの統合後もこのポートでのローカル
        # フロントエンド開発を継続できるようにするため。
        "http://localhost:5500",
        "http://127.0.0.1:5500",
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
app.include_router(admin_auth.router, prefix="/api/admin", tags=["admin"])
app.include_router(admin_health.router, prefix="/api/admin", tags=["admin"])
app.include_router(admin_review.router, prefix="/api/admin", tags=["admin"])
app.include_router(admin_config.router, prefix="/api/admin", tags=["admin"])

# 【統合(案B): apps/persona_main_function からのマージ】各ルーター内の@router
# デコレータが既に絶対パス(/v1/personas, /v1/generate等)を宣言しているため、
# prefixは付与しない(元のapps/persona_main_function/main.pyと同じ登録規約)。
# generate.py→api/routers/persona_generate.pyへリネーム済み(このファイル自身の
# 既存generate.router(/api/generate)との名前衝突を避けるため)。
app.include_router(persona_generate.router, tags=["persona_generate"])
app.include_router(personas.router, tags=["personas"])
app.include_router(timeline.router, tags=["persona_timeline"])
app.include_router(unlock.router, tags=["persona_unlock"])


@app.get("/healthz")
def persona_healthz():
    """旧apps/persona_main_function/main.pyのヘルスチェックと同一パス・同一応答形状。
    Cloud Runの起動プローブ設定を変更せずに統合できるよう、/api/healthとは別に
    このパスも維持する。"""
    return {"status": "ok"}


@app.get("/api/health")
def healthz():
    # firestore_restore: Cloud Run起動時のFirestore復元(Phase5.5)の進捗を
    # 運用監視から見えるようにする。restoring中でもこのエンドポイント自体は
    # 常に200を返す(_firestore_restore_gateの対象外パスのため)。
    return {"ok": True, "firestore_restore": _firestore_restore_status}

# 2. 旧UIの静的ファイルマウント（特化パスを先に）
app.mount("/cic", StaticFiles(directory=str(LEGACY_DIR), html=True), name="legacy")

# 3. 新UIの静的ファイルマウント（キャッチオールは必ず最後）
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")





# force ci trigger 20260810091256

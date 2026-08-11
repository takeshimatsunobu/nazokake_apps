"""コスト管理ルーター(Ⅲ コスト管理、Phase 3)。

GET  /costs               : system_costs コレクション(API/LLMトークンコスト自己ログ、
                             nazokake_core.cost_calculator参照)を timestamp 降順で
                             最大100件取得し、SystemCostLog のリスト(JSON)として返す。
GET  /costs/dashboard     : 同じ最大100件から合計金額・予算消化率を算出し、
                             Jinja2テンプレートでHTMLダッシュボードを描画する。
GET  /gcp-costs           : Firestore(system_gcp_costs/latest)を返すだけの薄い
                             ラッパー。管理画面(Ⅲペイン)から直接叩かれる。
POST /jobs/sync-gcp-costs : BigQuery Billing Exportから前日・前々日分を集計し、
                             system_gcp_costs/latest・system_gcp_costs_history/{date}
                             へアトミックに書き込む日次バッチジョブ。

【Phase1で発見したセキュリティホールの是正】以前は/costs・/costs/dashboardの
どちらにもDepends(verify_admin_token)が付いておらず、無認証で叩けた。本フェーズで
他のadmin系エンドポイントと同じ認証ゲートを追加する(この変更に伴い、admin.htmlの
window.open()による/costs/dashboard直接リンクは廃止した。Bearerトークンを
Authorizationヘッダで送れないブラウザの素朴なnavigateとはそもそも両立しないため。
Ⅲペインは/costs・/gcp-costsをfetchで叩く埋め込みダッシュボードへ置き換えている)。
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.templating import Jinja2Templates
from firebase_admin import firestore

from api.deps import get_db, handle_exceptions, verify_admin_token
from models.schemas import (
    GcpCostBreakdownItem,
    GcpCostsLatestResponse,
    GcpCostsSyncResponse,
)
from nazokake_core.schemas import SystemCostLog

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 当月の予算上限(円)。環境変数 MONTHLY_BUDGET_JPY で上書き可能。
BUDGET_LIMIT_JPY = float(os.environ.get("MONTHLY_BUDGET_JPY", 5000.0))

GCP_COSTS_LATEST_COLLECTION = "system_gcp_costs"
GCP_COSTS_LATEST_DOC = "latest"
GCP_COSTS_HISTORY_COLLECTION = "system_gcp_costs_history"
GCP_COSTS_SCHEMA_VERSION = "1.0"


def _fetch_costs_sync(db, limit: int) -> list:
    """Firestoreのstream()を同期的に実行し、リスト化して返すヘルパー関数"""
    query = db.collection("system_costs").order_by(
        "timestamp", direction=firestore.Query.DESCENDING
    )
    return list(query.limit(limit).stream())


async def _fetch_recent_costs(db, limit: int = 100) -> list[SystemCostLog]:
    docs = await asyncio.to_thread(_fetch_costs_sync, db, limit)
    return [SystemCostLog(**doc.to_dict()) for doc in docs]


async def is_budget_exceeded(db) -> bool:
    """直近のコストログ合計が BUDGET_LIMIT_JPY を超過しているかを判定する(ソフトリミット)。"""
    costs = await _fetch_recent_costs(db)
    total_cost_jpy = sum(c.calculated_cost_jpy for c in costs)
    return total_cost_jpy > BUDGET_LIMIT_JPY


@router.get("/costs")
@handle_exceptions
async def get_costs(
    admin_token: dict = Depends(verify_admin_token), db=Depends(get_db)
):
    costs = await _fetch_recent_costs(db)
    return [c.model_dump() for c in costs]


@router.get("/costs/dashboard")
@handle_exceptions
async def get_costs_dashboard(
    request: Request,
    admin_token: dict = Depends(verify_admin_token),
    db=Depends(get_db),
):
    costs = await _fetch_recent_costs(db)
    total_cost_jpy = sum(c.calculated_cost_jpy for c in costs)
    budget_percentage = (
        (total_cost_jpy / BUDGET_LIMIT_JPY * 100) if BUDGET_LIMIT_JPY else 0.0
    )
    return templates.TemplateResponse(
        "costs_dashboard.html",
        {
            "request": request,
            "costs": costs,
            "total_cost_jpy": total_cost_jpy,
            "budget_limit_jpy": BUDGET_LIMIT_JPY,
            "budget_percentage": budget_percentage,
        },
    )


# ------------------------------------------------------------
# GCPインフラコスト(BigQuery Billing Export日次集計)
# ------------------------------------------------------------


@router.get("/gcp-costs", response_model=GcpCostsLatestResponse)
@handle_exceptions
async def get_gcp_costs(
    admin_token: dict = Depends(verify_admin_token), db=Depends(get_db)
):
    """system_gcp_costs/latest を返すだけの薄いラッパー。BigQueryへは一切触れない
    (管理画面からの毎回のアクセスでBQのスキャンコストが嵩むのを避けるための設計、
    実際の集計はsync_gcp_costs()が日次バッチとして行う)。
    """

    def _get_sync():
        return db.collection(GCP_COSTS_LATEST_COLLECTION).document(GCP_COSTS_LATEST_DOC).get()

    snapshot = await asyncio.to_thread(_get_sync)
    if not snapshot.exists:
        # まだ一度も日次バッチが実行されていない(ローカル開発時や導入直後)。
        # 空のレスポンスで縮退運転する(エラーにはしない)。
        return GcpCostsLatestResponse()

    data = snapshot.to_dict() or {}
    return GcpCostsLatestResponse(**data)


def _resolve_billing_table() -> str:
    """BigQuery Billing Exportのフルテーブル名(project.dataset.table)を環境変数から
    取得する。GCPコンソールでのBilling Export有効化(手動・1回限りの設定)が済んで
    いない限りこの値は存在しないため、未設定時は明確なエラーメッセージで即座に
    失敗させる(サーバー起動自体は絶対にブロックしない。この関数はエンドポイント
    呼び出し時にのみ評価される)。
    """
    table = os.environ.get("GCP_BILLING_EXPORT_TABLE", "").strip()
    if not table:
        raise HTTPException(
            status_code=503,
            detail=(
                "GCP_BILLING_EXPORT_TABLE が未設定です。GCPコンソールでBilling Export"
                "をBigQueryへ有効化した上で、生成されたテーブルのフルパス"
                "(project.dataset.gcp_billing_export_v1_XXXXXX)を環境変数へ設定してください。"
            ),
        )
    return table


def _verify_sync_secret(x_cost_sync_secret: str | None) -> None:
    """このジョブエンドポイントの簡易認証。

    【将来の計画(要件に明記の通り)】本番ではCloud SchedulerのOIDCトークンによる
    呼び出しを想定しているが、evaluator/backendのCloud Runサービス自体は
    (フロントエンド配信も兼ねるため)--allow-unauthenticatedで公開されており、
    Cloud Run側のIAM invoker権限だけではこのエンドポイント単体を保護できない
    (IAM invoker制御はサービス単位であり、パス単位では効かない)。そのため
    現時点では共有シークレット(環境変数 GCP_COST_SYNC_SECRET とヘッダー
    X-Cost-Sync-Secret の一致)による簡易認証を実装する。Cloud SchedulerのOIDC
    トークンをアプリケーションコード側で検証する(google.oauth2.id_token.verify_oauth2_token
    でaud/iss/emailを検証する)方式への切り替えは、実際にCloud Schedulerを
    配線する際の自然な後続タスクとして明記しておく。
    """
    expected = os.environ.get("GCP_COST_SYNC_SECRET", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="GCP_COST_SYNC_SECRET が未設定のため、このジョブエンドポイントは無効化されています。",
        )
    if not x_cost_sync_secret or x_cost_sync_secret != expected:
        raise HTTPException(status_code=401, detail="X-Cost-Sync-Secret が不正です。")


def _query_billing_export_sync(table: str, dates: list[str]) -> list[dict]:
    """BigQueryへ同期的に問い合わせる(呼び出し元でasyncio.to_threadすること)。

    【防御的インポート】google-cloud-bigqueryは(1) pip未インストール、
    (2) ローカル開発機にADC(Application Default Credentials)が無い、のどちらでも
    サーバー起動そのものをクラッシュさせてはならない。そのためこの関数の内部で
    初めてimportし、失敗はすべて呼び出し元(sync_gcp_costs)がHTTPExceptionへ変換する
    (モジュールのトップレベルでimportしないのは、admin_costs.py自体のimportが
    google-cloud-bigquery未インストール環境でサーバー起動を道連れにしないため)。
    """
    from google.cloud import bigquery

    client = bigquery.Client()
    query = f"""
        SELECT
            DATE(usage_start_time) AS usage_date,
            service.description AS service_description,
            ANY_VALUE(currency) AS currency,
            SUM(cost) AS total_cost
        FROM `{table}`
        WHERE DATE(usage_start_time) IN UNNEST(@target_dates)
        GROUP BY usage_date, service_description
        ORDER BY usage_date, total_cost DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("target_dates", "DATE", dates),
        ]
    )
    rows = client.query(query, job_config=job_config).result()
    return [
        {
            "usage_date": row["usage_date"].isoformat(),
            "service_description": row["service_description"] or "(不明)",
            "currency": row["currency"],
            "total_cost": float(row["total_cost"] or 0.0),
        }
        for row in rows
    ]


def _write_gcp_costs_batch_sync(db, summaries: dict[str, dict], generated_at: str) -> None:
    """system_gcp_costs/latest と system_gcp_costs_history/{date}(複数件)を
    単一のFirestore WriteBatchでアトミックに書き込む(全件成功 or 全件失敗)。
    """
    batch = db.batch()

    for date_str, summary in summaries.items():
        history_ref = db.collection(GCP_COSTS_HISTORY_COLLECTION).document(date_str)
        batch.set(history_ref, summary)

    if summaries:
        latest_date = max(summaries.keys())
        latest_ref = db.collection(GCP_COSTS_LATEST_COLLECTION).document(GCP_COSTS_LATEST_DOC)
        batch.set(latest_ref, summaries[latest_date])

    batch.commit()


@router.post("/jobs/sync-gcp-costs", response_model=GcpCostsSyncResponse)
@handle_exceptions
async def sync_gcp_costs(
    x_cost_sync_secret: str | None = Header(default=None),
    db=Depends(get_db),
):
    """BigQuery Billing Exportから「前日・前々日」分を service.description ごとに
    SUM(cost)で集計し、Firestoreへアトミックに書き込む日次バッチジョブ。

    前日・前々日の2日分を毎回まとめて再計算する理由: Billing Exportには数時間の
    反映遅延があるため、深夜0時台の実行では「前日」分がまだ確定していないことが
    ある。2日分を毎回冪等に洗い替えることで、遅延到着したデータも次回実行時に
    自動的に補正される(1日分だけを都度差分更新する設計より単純で壊れにくい)。
    """
    _verify_sync_secret(x_cost_sync_secret)
    table = _resolve_billing_table()

    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    day_before_yesterday = today - timedelta(days=2)
    target_dates = [day_before_yesterday.isoformat(), yesterday.isoformat()]

    try:
        rows = await asyncio.to_thread(_query_billing_export_sync, table, target_dates)
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"BigQueryへの問い合わせに失敗しました: {e}"
        )

    generated_at = datetime.now(timezone.utc).isoformat()
    summaries: dict[str, dict] = {}
    for row in rows:
        date_str = row["usage_date"]
        summary = summaries.setdefault(
            date_str,
            {
                "schema_version": GCP_COSTS_SCHEMA_VERSION,
                "date": date_str,
                "currency": row["currency"],
                "total_cost": 0.0,
                "breakdown": [],
                "generated_at": generated_at,
            },
        )
        summary["total_cost"] += row["total_cost"]
        summary["breakdown"].append(
            GcpCostBreakdownItem(
                service_description=row["service_description"], cost=row["total_cost"]
            ).model_dump()
        )

    # 対象日にBilling Export側のデータが1件も無かった場合でも、0円のプレースホルダーを
    # 書き込んでおく(latestが「まだ一度も実行されていない」のか「実行したが0円だった」
    # のかをUI側が区別できるようにする)。
    for date_str in target_dates:
        summaries.setdefault(
            date_str,
            {
                "schema_version": GCP_COSTS_SCHEMA_VERSION,
                "date": date_str,
                "currency": None,
                "total_cost": 0.0,
                "breakdown": [],
                "generated_at": generated_at,
            },
        )

    await asyncio.to_thread(_write_gcp_costs_batch_sync, db, summaries, generated_at)

    return GcpCostsSyncResponse(
        status="success",
        message=f"{len(summaries)}日分のGCPコストを集計しました",
        synced_dates=sorted(summaries.keys()),
    )

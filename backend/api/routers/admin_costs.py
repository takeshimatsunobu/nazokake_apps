"""コスト管理ルーター(Phase 3)。

GET /costs           : system_costs コレクションを timestamp 降順で最大100件取得し、
                        SystemCostLog のリスト(JSON)として返す。
GET /costs/dashboard : 同じ最大100件から合計金額・予算消化率を算出し、
                        Jinja2テンプレートでHTMLダッシュボードを描画する。
"""

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from firebase_admin import firestore

from api.deps import get_db, handle_exceptions
from nazokake_core.schemas import SystemCostLog

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 当月の予算上限(円)。環境変数 MONTHLY_BUDGET_JPY で上書き可能。
BUDGET_LIMIT_JPY = float(os.environ.get("MONTHLY_BUDGET_JPY", 5000.0))


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
async def get_costs(db=Depends(get_db)):
    costs = await _fetch_recent_costs(db)
    return [c.model_dump() for c in costs]


@router.get("/costs/dashboard")
@handle_exceptions
async def get_costs_dashboard(request: Request, db=Depends(get_db)):
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

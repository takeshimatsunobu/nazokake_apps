"""
cost_calculator.py
===================
LLM API利用のトークン数をUSD建て単価表から日本円(JPY)へ換算する共通ロジック。
領域B(evaluator)・領域C(batch_factory)の両方から利用される想定。
"""
from __future__ import annotations
import asyncio
import os

from .schemas import SystemCostLog

# ------------------------------------------------------------
# 価格テーブル (USD / 1M tokens)
# キーは calculate_token_cost_jpy() / async_log_system_cost() に渡す
# model_name(= 呼び出し元が指定する具体的なモデル識別子)と一致させる。
# 表にないキー(Ollama/Server 等のローカル実行系を含む)はコスト0円として扱う。
# ------------------------------------------------------------
PRICE_TABLE_USD_PER_M_TOKENS: dict[str, tuple[float, float]] = {
    # モデル名: (input USD/1M tokens, output USD/1M tokens)
    "claude-3-5-sonnet": (3.0, 15.0),
    "gemini-1.5-pro": (1.25, 5.0),
    "gemini-2.5-flash": (0.075, 0.3),
}

DEFAULT_EXCHANGE_RATE_USD_JPY = 160.0


def _get_exchange_rate() -> float:
    """環境変数 EXCHANGE_RATE_USD_JPY からドル円レートを取得する(未設定時は既定値)。"""
    try:
        return float(os.environ.get("EXCHANGE_RATE_USD_JPY", DEFAULT_EXCHANGE_RATE_USD_JPY))
    except ValueError:
        return DEFAULT_EXCHANGE_RATE_USD_JPY


def calculate_token_cost_jpy(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """トークン数を指定モデルの単価表とドル円レートで日本円に換算する。

    価格表に存在しないmodel_name(Ollama/Server等のローカル実行系)は0円を返す。
    """
    input_price, output_price = PRICE_TABLE_USD_PER_M_TOKENS.get(model_name, (0.0, 0.0))
    cost_usd = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
    cost_jpy = cost_usd * _get_exchange_rate()
    return round(cost_jpy, 4)


async def async_log_system_cost(
    db,
    service_type: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    execution_time_sec: float = 0.0,
) -> SystemCostLog:
    """コストを計算し、SystemCostLogとしてバリデーションした上でFirestoreへ非同期保存する。

    db の Firestore 書き込み自体は同期APIのため、asyncio.to_thread でイベントループを塞がない。
    """
    cost_jpy = calculate_token_cost_jpy(service_type, input_tokens, output_tokens)
    log = SystemCostLog(
        service_type=service_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        execution_time_sec=execution_time_sec,
        calculated_cost_jpy=cost_jpy,
    )
    await asyncio.to_thread(db.collection("system_costs").add, log.model_dump())
    return log

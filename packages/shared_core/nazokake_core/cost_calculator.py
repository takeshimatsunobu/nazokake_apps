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
    # generation.py の fallback_model として実運用で使用中(発見時点で価格表に
    # 未登録だったため、Gemini生成コストが常に0円扱いになっていた欠落を修正)。
    # 単価は暫定推定値。実際の請求明細と照合の上、必要に応じて更新すること。
    "gemini-3.5-flash": (0.10, 0.40),
    # ELYZAタイムアウト時のGemini Flash Lite代打モード(apps/evaluator/backend/
    # api/routers/generate.py::process_elyza_pinch_hitter)で実運用使用中。
    # gemini-3.5-flashの約半額という一般的なFlash-Lite/Flash比率を踏まえた
    # 暫定推定値(実測でこのモデル固有の価格を確認できていないため)。
    # 実際の請求明細と照合の上、必要に応じて更新すること。
    "gemini-3.5-flash-lite": (0.05, 0.20),
    # persona_feature_plan_v3.md Phase6 §7.4: マイペルソナ「ドラフト生成」
    # (apps/persona_main_function/services/persona_draft.py)専用のservice_typeキー。
    # モデル自体は"gemini-3.5-flash"と同じだが、計画書が指定する単価
    # (入力$1.50/1M、出力$9.00/1M)が既存の"gemini-3.5-flash"エントリ
    # (evaluatorの本番生成コスト計測で実運用中、暫定推定値$0.10/$0.40)と
    # 食い違っていたため、既存エントリを上書きせず別キーとして登録する
    # (上書きするとevaluator側の全生成コスト計測に影響してしまうため)。
    "persona_draft_gemini": (1.50, 9.00),
}

DEFAULT_EXCHANGE_RATE_USD_JPY = 160.0

# ------------------------------------------------------------
# ローカルサーバー稼働コスト(電気代)の単価
# API課金の対象外であるOllama/自前サーバー等の「見えないコスト」を近似する。
# ------------------------------------------------------------
DEFAULT_SERVER_COST_PER_HOUR_JPY = 5.0

# service_type がこの集合(大文字小文字を区別しない)に一致する場合は
# トークン単価ではなく稼働時間ベースの電気代として計算する。
LOCAL_SERVICE_TYPES = {"ollama", "server"}


def _get_exchange_rate() -> float:
    """環境変数 EXCHANGE_RATE_USD_JPY からドル円レートを取得する(未設定時は既定値)。"""
    try:
        return float(os.environ.get("EXCHANGE_RATE_USD_JPY", DEFAULT_EXCHANGE_RATE_USD_JPY))
    except ValueError:
        return DEFAULT_EXCHANGE_RATE_USD_JPY


def _get_server_cost_per_hour() -> float:
    """環境変数 SERVER_COST_PER_HOUR_JPY からローカルサーバーの時間単価を取得する(未設定時は既定値)。"""
    try:
        return float(os.environ.get("SERVER_COST_PER_HOUR_JPY", DEFAULT_SERVER_COST_PER_HOUR_JPY))
    except ValueError:
        return DEFAULT_SERVER_COST_PER_HOUR_JPY


def calculate_token_cost_jpy(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """トークン数を指定モデルの単価表とドル円レートで日本円に換算する。

    価格表に存在しないmodel_name(Ollama/Server等のローカル実行系)は0円を返す。
    """
    input_price, output_price = PRICE_TABLE_USD_PER_M_TOKENS.get(model_name, (0.0, 0.0))
    cost_usd = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
    cost_jpy = cost_usd * _get_exchange_rate()
    return round(cost_jpy, 4)


def calculate_server_cost_jpy(execution_time_sec: float) -> float:
    """実行時間(秒)をSERVER_COST_PER_HOUR_JPYの時間単価で日本円に換算する(ローカル稼働の電気代)。"""
    execution_time_hours = execution_time_sec / 3600
    cost_jpy = execution_time_hours * _get_server_cost_per_hour()
    return round(cost_jpy, 4)


async def async_log_system_cost(
    db,
    service_type: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    execution_time_sec: float = 0.0,
    success: bool = True,
) -> SystemCostLog:
    """コストを計算し、SystemCostLogとしてバリデーションした上でFirestoreへ非同期保存する。

    service_type が Ollama/Server 等のローカル実行系であれば稼働時間ベースの電気代
    (calculate_server_cost_jpy)、それ以外(Claude/Gemini等のAPIモデル名)であれば
    トークン単価ベースの課金額(calculate_token_cost_jpy)で算出する。
    db の Firestore 書き込み自体は同期APIのため、asyncio.to_thread でイベントループを塞がない。

    【Phase1追加】success=False で呼ぶと「試行はしたが失敗した」呼び出しとして
    記録される(通常はトークン数不明のため0のまま、コストは掛からなかったものと
    して0円になる)。管理コクピットの「APIエラー率」タイルはこのフィールドを
    集計するだけで、Cloud Logging等の追加インフラ無しにエラー率を算出できる。
    """
    if service_type.lower() in LOCAL_SERVICE_TYPES:
        cost_jpy = calculate_server_cost_jpy(execution_time_sec)
    else:
        cost_jpy = calculate_token_cost_jpy(service_type, input_tokens, output_tokens)
    log = SystemCostLog(
        service_type=service_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        execution_time_sec=execution_time_sec,
        calculated_cost_jpy=cost_jpy,
        success=success,
    )
    await asyncio.to_thread(db.collection("system_costs").add, log.model_dump())
    return log

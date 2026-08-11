"""services/cost_logging.py
============================
Step1推定・Step2生成のGemini呼び出しコスト計装(Phase3)。

【ファクト調査で判明した穴】apps/persona_router は稼働開始以来、Gemini呼び出しの
トークン量・コストを一切記録していなかった(apps/evaluator/backend側は
services/evaluation.py::_log_evaluation_cost / services/generation.py::_log_generation_cost
で最初から計装済みだったのに対し、persona_router側だけが計測ゼロの状態だった)。

apps/evaluator/backend側の同名ヘルパーと同じ設計(失敗しても本体の生成処理は
継続する、nazokake_core.cost_calculator経由でsystem_costsへ非同期記録)を
そのまま踏襲する。
"""
from __future__ import annotations

from firebase_admin import firestore


async def log_step_cost(
    service_type: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    execution_time_sec: float = 0.0,
    success: bool = True,
) -> None:
    """コストログの記録に失敗しても、呼び出し元のなぞかけ生成処理には一切影響させない。"""
    try:
        from nazokake_core.cost_calculator import async_log_system_cost

        db = firestore.client()
        await async_log_system_cost(
            db,
            service_type=service_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            execution_time_sec=execution_time_sec,
            success=success,
        )
    except Exception as e:
        print(f"⚠️ [persona_router] コストログ記録に失敗しました(生成処理には影響なし): {e}")

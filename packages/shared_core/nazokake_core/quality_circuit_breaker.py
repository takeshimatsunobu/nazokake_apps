"""
nazokake_core/quality_circuit_breaker.py
===========================================
Agent自身の推論出力品質のサイレント・デグレード検知(instructions/182)。

インフラ死活監視(Docker不在・VRAM枯渇等、tools/preflight_check.pyのFail-Closed)とは
別に、Agentの推論出力そのものが静かに劣化していくケースを検知する:
  - なぞかけ評価スコアがN回連続でスケールの最高/最低に偏っている
    (record_evaluation_score)。
  - 同一のエラー・パース失敗がN回連続で発生している(record_pipeline_outcome)。

状態の更新(連続回数のカウント・しきい値到達判定)自体はnazokake_core.databaseの
_record_evaluation_score_event()/_record_pipeline_outcome_event()が担い、この
モジュールはその結果(tripped)を見て実際にQualityCircuitBreakerErrorを送出するか
どうかを判断する責務のみを持つ(ORM/DB層は「何が異常か」を知らず、この層だけが
「異常を検知したら中断する」というポリシーを持つ、という関心の分離)。

呼び出し元(apps/batch_factory/batch/main.py等、自律ループの最上位)はこの例外を
捕捉せず素通りさせることで、インフラのFail-Closed原則と同様にプロセス自体を
強制中断(sys.exit(1)相当)させる。一方、apps/evaluator/backend(常駐のFastAPI
サーバー)のようにプロセス自体を中断させてはならない呼び出し元は、既存の
try/except(1件のリクエスト単位でのエラー処理)の内側でこの例外を自然に吸収する
(呼び出し元ごとに例外処理の粒度を変える必要はなく、このモジュール自身は常に
同じ振る舞いをする)。
"""

from __future__ import annotations

from .database import (
    async_record_evaluation_score_event,
    async_record_pipeline_outcome_event,
    sync_record_evaluation_score_event,
    sync_record_pipeline_outcome_event,
)
from .exceptions import QualityCircuitBreakerError

# 「N回連続」のNの既定値。なぞかけ評価スコアの極端値連続・同一エラーの連続発生の
# いずれもこの値を既定のしきい値とする(呼び出し元がthreshold引数で上書き可能)。
DEFAULT_THRESHOLD = 5


def _direction_and_extremity(s_total: float, scale_max: float) -> tuple[bool, str]:
    """s_totalがスケールの最高値/最低値に達している(極端)かどうかと、その方向を判定する。"""
    if s_total >= scale_max:
        return True, "high"
    if s_total <= 0.0:
        return True, "low"
    return False, ""


def _raise_if_tripped(pipeline_id: str, kind: str, result: dict) -> None:
    if not result["tripped"]:
        return
    raise QualityCircuitBreakerError(
        f"🚨 [Quality Circuit Breaker] pipeline_id={pipeline_id!r} で{kind}が"
        f"{result['consecutive_count']}回連続で発生しました。サイレント・デグレードの"
        "兆候とみなし、自律稼働を中断します。"
    )


async def async_record_evaluation_score(
    pipeline_id: str, s_total: float, *, scale_max: float = 5.0, threshold: int = DEFAULT_THRESHOLD
) -> None:
    """なぞかけ評価スコアを1件記録し、N回連続で極端値(スケール最高/最低)に偏って
    いる場合はQualityCircuitBreakerErrorを送出する。
    """
    is_extreme, direction = _direction_and_extremity(s_total, scale_max)
    result = await async_record_evaluation_score_event(
        pipeline_id, is_extreme=is_extreme, direction=direction or None, threshold=threshold
    )
    _raise_if_tripped(pipeline_id, "評価スコアの極端値への偏り", result)


def sync_record_evaluation_score(
    pipeline_id: str, s_total: float, *, scale_max: float = 5.0, threshold: int = DEFAULT_THRESHOLD
) -> None:
    """async_record_evaluation_score()の同期版(apps/batch_factory向け)。"""
    is_extreme, direction = _direction_and_extremity(s_total, scale_max)
    result = sync_record_evaluation_score_event(
        pipeline_id, is_extreme=is_extreme, direction=direction or None, threshold=threshold
    )
    _raise_if_tripped(pipeline_id, "評価スコアの極端値への偏り", result)


async def async_record_pipeline_outcome(
    pipeline_id: str, error_signature: str | None, *, threshold: int = DEFAULT_THRESHOLD
) -> None:
    """1回の試行結果を記録する。error_signature=Noneは成功(連続回数をリセット)を、
    非Noneは失敗(その文字列を「同一のエラー・パース失敗」の判定キーとする)を意味する。
    N回連続で同一のerror_signatureが記録された場合はQualityCircuitBreakerErrorを送出する。
    """
    result = await async_record_pipeline_outcome_event(
        pipeline_id, error_signature=error_signature, threshold=threshold
    )
    _raise_if_tripped(pipeline_id, "同一のエラー・パース失敗", result)


def sync_record_pipeline_outcome(
    pipeline_id: str, error_signature: str | None, *, threshold: int = DEFAULT_THRESHOLD
) -> None:
    """async_record_pipeline_outcome()の同期版(apps/batch_factory向け)。"""
    result = sync_record_pipeline_outcome_event(
        pipeline_id, error_signature=error_signature, threshold=threshold
    )
    _raise_if_tripped(pipeline_id, "同一のエラー・パース失敗", result)

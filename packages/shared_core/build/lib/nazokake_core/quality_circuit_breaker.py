"""
nazokake_core/quality_circuit_breaker.py
===========================================
Agent自身の推論出力品質のサイレント・デグレード検知(instructions/182、
スライディングウィンドウ方式への是正はinstructions/183)。

インフラ死活監視(Docker不在・VRAM枯渇等、tools/preflight_check.pyのFail-Closed)とは
別に、Agentの推論出力そのものが静かに劣化していくケースを検知する:
  - なぞかけ評価スコアが直近window_size件中anomaly_threshold件以上でスケールの
    最高/最低に偏っている(record_evaluation_score)。
  - 生成/評価の試行が直近window_size件中anomaly_threshold件以上失敗している
    (record_pipeline_outcome)。

状態の更新(スライディングウィンドウの更新・しきい値到達判定)自体はnazokake_core.databaseの
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

# スライディングウィンドウ方式(instructions/183)の既定値。なぞかけ評価スコアの
# 極端値・パイプライン試行の失敗のいずれも、直近DEFAULT_WINDOW_SIZE件のうち
# DEFAULT_ANOMALY_THRESHOLD件以上が異常であればTripとみなす(呼び出し元が
# window_size/anomaly_threshold引数で上書き可能)。「連続N回」方式は確率的モデルの
# ノイズ(まぐれ当たり1回)だけで連続回数がリセットされ検知漏れを起こすため廃止した。
DEFAULT_WINDOW_SIZE = 10
DEFAULT_ANOMALY_THRESHOLD = 8


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
        f"直近{result['window_size']}回中{result['anomaly_count']}回発生しました。"
        "サイレント・デグレード(またはFlapping)の兆候とみなし、自律稼働を中断します。"
    )


async def async_record_evaluation_score(
    pipeline_id: str,
    s_total: float,
    *,
    scale_max: float = 5.0,
    window_size: int = DEFAULT_WINDOW_SIZE,
    anomaly_threshold: int = DEFAULT_ANOMALY_THRESHOLD,
) -> None:
    """なぞかけ評価スコアを1件記録し、直近window_size件中anomaly_threshold件以上が
    極端値(スケール最高/最低)に偏っている場合はQualityCircuitBreakerErrorを送出する。
    """
    is_extreme, direction = _direction_and_extremity(s_total, scale_max)
    result = await async_record_evaluation_score_event(
        pipeline_id,
        is_extreme=is_extreme,
        direction=direction or None,
        window_size=window_size,
        anomaly_threshold=anomaly_threshold,
    )
    _raise_if_tripped(pipeline_id, "評価スコアの極端値への偏り", result)


def sync_record_evaluation_score(
    pipeline_id: str,
    s_total: float,
    *,
    scale_max: float = 5.0,
    window_size: int = DEFAULT_WINDOW_SIZE,
    anomaly_threshold: int = DEFAULT_ANOMALY_THRESHOLD,
) -> None:
    """async_record_evaluation_score()の同期版(apps/batch_factory向け)。"""
    is_extreme, direction = _direction_and_extremity(s_total, scale_max)
    result = sync_record_evaluation_score_event(
        pipeline_id,
        is_extreme=is_extreme,
        direction=direction or None,
        window_size=window_size,
        anomaly_threshold=anomaly_threshold,
    )
    _raise_if_tripped(pipeline_id, "評価スコアの極端値への偏り", result)


async def async_record_pipeline_outcome(
    pipeline_id: str,
    error_signature: str | None,
    *,
    window_size: int = DEFAULT_WINDOW_SIZE,
    anomaly_threshold: int = DEFAULT_ANOMALY_THRESHOLD,
) -> None:
    """1回の試行結果を記録する。error_signature=Noneは成功(ウィンドウに"正常"を積む)を、
    非Noneは失敗(その文字列を診断用のlast_error_signatureとして保持する、Trip判定は
    シグネチャの一致を問わない)を意味する。直近window_size件中anomaly_threshold件以上が
    失敗であればQualityCircuitBreakerErrorを送出する。
    """
    result = await async_record_pipeline_outcome_event(
        pipeline_id,
        error_signature=error_signature,
        window_size=window_size,
        anomaly_threshold=anomaly_threshold,
    )
    _raise_if_tripped(pipeline_id, "生成/評価の試行失敗", result)


def sync_record_pipeline_outcome(
    pipeline_id: str,
    error_signature: str | None,
    *,
    window_size: int = DEFAULT_WINDOW_SIZE,
    anomaly_threshold: int = DEFAULT_ANOMALY_THRESHOLD,
) -> None:
    """async_record_pipeline_outcome()の同期版(apps/batch_factory向け)。"""
    result = sync_record_pipeline_outcome_event(
        pipeline_id,
        error_signature=error_signature,
        window_size=window_size,
        anomaly_threshold=anomaly_threshold,
    )
    _raise_if_tripped(pipeline_id, "生成/評価の試行失敗", result)

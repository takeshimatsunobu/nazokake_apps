"""
nazokake_core/exceptions.py
==============================
apps/evaluator・apps/batch_factory・tools/ の全プロセスが共有するドメイン固有例外
(instructions/182)。

tools/exceptions.py(tools/*.py専用)とは別に、nazokake_core側にも用意する。
apps/evaluator/backend・apps/batch_factory は別venv・別プロセスであり、tools/ への
依存を持たない(唯一の共有依存はこのnazokake_coreパッケージのみ)ため、複数プロセスに
またがる例外はここで定義しないと、tools/ を経由しないapps/*からは捕捉できない。
"""

from __future__ import annotations


class QualityCircuitBreakerError(Exception):
    """Agent自身の推論出力品質のサイレント・デグレードを検知した際に送出する例外。

    なぞかけ評価スコアがN回連続で極端な値(最高/最低)に偏っている、または同一の
    エラー・パース失敗がN回連続で発生している場合に
    nazokake_core.quality_circuit_breaker から送出される。インフラ死活監視の
    Fail-Closed原則(tools/preflight_check.py)と同様、呼び出し元の自律ループ最上位
    (apps/batch_factory/batch/main.py等)はこれを捕捉せず素通りさせることで、
    プロセス自体を強制中断(sys.exit(1)相当)させる。
    """

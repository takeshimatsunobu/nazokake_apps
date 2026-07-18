"""
tools/exceptions.py
======================
Nazo-Agent/MLOpsパイプライン全体で共有するドメイン固有例外(instructions/139)。

汎用の RuntimeError で「インフラ起因の異常(Docker不在・VRAM枯渇等)」と
「ロジック起因の異常(サブプロセスのクラッシュ等)」を区別なく送出していたため、
呼び出し元の最上位層(各MLOpsパイプラインのmain())がOSの終了コード
(インフラ異常: 125、実行異常: 1)へ決定論的にマッピングできなかった。
この階層構造により、except節の型だけで両者を判別できるようにする。
"""

from __future__ import annotations


class NazoAgentBaseError(Exception):
    """Nazo-Agent/MLOpsパイプライン全体が送出するドメイン固有例外の基底クラス。"""


class MLOpsInfrastructureError(NazoAgentBaseError):
    """VRAM枯渇やDocker不在等、インフラ起因で処理を継続できない異常。

    最上位層ではこれを終了コード125(Docker CLI慣例に倣ったインフラエラー専用
    コード、instructions/136)へマッピングする。
    """


class PipelineExecutionError(NazoAgentBaseError):
    """サブプロセスのクラッシュ等、ロジック起因で処理が異常終了した異常。

    最上位層ではこれを終了コード1(通常のアプリケーションエラー)へマッピングする。
    """

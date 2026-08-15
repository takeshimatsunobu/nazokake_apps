"""
personas.py (後方互換シム)
=============
本体は packages/shared_core/nazokake_core/personas.py へ移動した(SSoT統一。
apps/persona_main_function 等の新規サービスも含め複数アプリから共有するため)。

このファイルは `from personas import PERSONAS` 形式の既存呼び出し元
(api/routers/generate.py、workers/ondemand_elyza_worker.py 等)を変更せずに
済ませるための再エクスポートのみを行う。新規コードは
`from nazokake_core.personas import PERSONAS, get_system_prompt` を直接使うこと。
"""

from nazokake_core.personas import PERSONAS, get_system_prompt  # noqa: F401

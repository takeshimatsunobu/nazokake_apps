"""
apps/persona_main_function/env.py
=============================
このアプリ専用の .env (apps/persona_main_function/.env) を読み込むヘルパー。

【GEMINI_API_KEY はこの.envに書かない】
nazokake_core.env_config.get_gemini_api_key() は「自分自身(packages/shared_core/
nazokake_core/)の場所」から上方向に .env を探索し、最初に見つかったものを
override=True で読み込む(apps/persona_main_function はその探索経路の祖先ディレクトリ
ではないため、ここに.envを置いても拾われない)。探索の結果、リポジトリルートの
.env(nazokake_apps/.env)が見つかる。GEMINI_API_KEYは同じ値が複数箇所の.envに
コピーされて食い違う事故が過去に実際に起きているため(apps/batch_factory構築時)、
ここでは意図的に再宣言せず、ルートの.envを唯一の情報源として頼る
(Cloud Run本番では.env自体が存在せず、プラットフォームが注入するos.environが
そのまま使われるため、この依存関係はローカル開発時のみ意味を持つ)。

このファイルでは、このアプリ固有の設定(STEP1_MODEL/STEP2_MODEL/GCP_PROJECT_ID等)
のみを読み込む。

【呼び出し順序が重要】
load_persona_main_function_env() は、`router`(→`llm`→nazokake_core.env_config)が
importされた"後"に呼ぶこと。env_config側の自動読み込み(モジュールimport時に
1回だけ発火する副作用)が先に走ってからでないと、override=Trueの後勝ち原則に
より、このアプリ固有の値が上書きされてしまう(main.pyでの呼び出し順序を参照)。
"""
from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def load_persona_main_function_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=APP_DIR / ".env", override=True)

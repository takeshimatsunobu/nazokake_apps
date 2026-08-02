"""
nazokake_core/env_config.py
==============================
シークレット/環境変数取得のSSoT(Single Source of Truth、instructions/303)。

【背景】GEMINI_API_KEYの読み込みロジック(os.environ.get呼び出しと、
python-dotenvによるルート.envの探索・ロード)が apps/evaluator/backend/core/config.py、
infra/data-sync-daemon/sync_daemon_entrypoint.py、apps/evaluator/backend/services/
(evaluation.py, generation.py, output_parser.py)、tools/nazo_agent.py、
tools/generate_doc_via_gemini.py 等に個別に散在しており、取得経路(.strip()の有無・
既定値・.envの探索パス計算)がファイルごとに微妙に異なっていた(DRY原則違反)。
apps/evaluator/backend/core/config.py 自身は「唯一の情報源(SSoT)」を自称する
コメントを持っていたが、tools/やinfra/配下の他プロセスからは参照されない
backend専用モジュールに過ぎず、実態としてSSoTになっていなかった。

本モジュールは apps/・tools/・infra/data-sync-daemon/ のいずれからも参照可能な
packages/shared_core(nazokake-core、既に上記すべてが依存関係として持つ共有コア)
に置くことで、真に唯一の取得窓口とする。

load_dotenv()はモジュールインポート時に一度だけ実行する。python-dotenvの既定
(override=False)により、Cloud Run/GCE Secret Manager・docker-compose env_file・
systemd Environment= 等、実行環境側が既に注入済みの値を .env の内容で上書きする
ことはない。.env が存在しない環境(Dockerイメージ内等)では無害にno-opし、その
環境が別途注入した環境変数がそのまま使われる。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# packages/shared_core/nazokake_core/env_config.py から3階層上がプロジェクトルート
# (nazokake_core -> shared_core -> packages -> <repo root>)。editable install
# (ローカル開発の既定)では__file__がこのソース位置のまま解決されるため正しく
# 機能する。非editableインストール(Docker/CI等)ではこの相対パス計算が実在しない
# 場所を指しうるが、load_dotenv()はファイル不在時に無害にno-opするだけであり、
# それらの環境は元々.envファイルではなく別経路(Secret Manager等)で環境変数を
# 注入するため実害はない。
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_PATH = _PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=_ENV_PATH)


def get_gemini_api_key() -> str | None:
    """GEMINI_API_KEYを取得する唯一の窓口。

    前後の空白は呼び出し元での重複ストリップを避けるためここで一律に除去する。
    未設定または空文字列の場合はNoneを返す(呼び出し元がそれぞれの文脈に応じた
    エラー処理・既定値フォールバックを行う)。
    """
    value = os.environ.get("GEMINI_API_KEY")
    return value.strip() if value and value.strip() else None

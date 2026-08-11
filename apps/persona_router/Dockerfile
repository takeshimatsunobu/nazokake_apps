# syntax=docker/dockerfile:1
#
# なぞかけペルソナルーター API (apps/persona_router/main.py) 用イメージ。
# ビルドコンテキストはリポジトリルートを想定する(apps/evaluator/Dockerfile と
# 全く同じ理由。[tool.uv.sources] の nazokake-core = { path = "../../packages/shared_core" }
# を解決するため、リポジトリと同じ相対ディレクトリ構造を再現してCOPYする必要がある)。
#
#   docker build -f apps/persona_router/Dockerfile -t nazokake-persona-router .
#
# 【重要】`gcloud run deploy --source apps/persona_router` のような、ソース
# ディレクトリ単体を渡す形の直接ビルドは使えない。gcloud run deployの--sourceは
# 指定ディレクトリそのものをビルドコンテキストにしてしまうため、上記の
# packages/shared_core への相対パス参照が解決できずビルド失敗する
# (cloudbuild.yaml のヘッダーコメントに記録されている、本リポジトリで実際に
# 踏んだ障害と同一パターン)。そのため本アプリも同じ回避策を踏襲し、リポジトリ
# ルートに置く cloudbuild.persona-router.yaml 経由でビルドする(デプロイ手順は
# このファイルと一緒に提示する)。
#
# nazokake_core(packages/shared_core)は、uv.lockが記録する相対パス依存を
# コンテナ内でも解決できるよう、リポジトリと同じ相対ディレクトリ構造
# (/build/apps/persona_router, /build/packages/shared_core)を再現してCOPYする。
#
# 【apps/evaluator/Dockerfileと同一の教訓を踏襲】
# - .venv内の各スクリプトのshebangは`uv sync`実行時のカレントディレクトリを
#   起点とした絶対パスで焼き込まれるため、runtimeステージでもbuilderと全く同じ
#   絶対パス(/build/apps/persona_router/.venv)へCOPYする。
# - 機密ファイル(.env・serviceAccountKey.json等)はリポジトリルート
#   .dockerignore(**/.env, **/serviceAccountKey.json 等を再帰的に除外)で
#   既に構造的にブロックされている。加えてこのDockerfileでは、apps/persona_router/
#   配下を丸ごとCOPYせず、実行に必要なファイル(main.py/env.py/api/models/services)
#   のみを個別にCOPYすることで、.env・frontend/・.venv等がそもそも
#   COPY命令の対象に一切登場しない(除外し忘れではなく構造的に含まれない設計)。

# ---- Builder: uvでロックファイル通りに依存関係を解決する(最終イメージにuv/ビルド
#      ツールを残さない) ----
FROM python:3.11-alpine AS builder

# uv公式配布バイナリを直接コピーする(pip経由でuv自身を導入すると、その解決自体が
# 非決定論的になり本末転倒なため)。このイメージはmusl/glibc両対応の静的バイナリ。
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Alpineのpython公式イメージにはコンパイラ/ヘッダーが同梱されないため、
# 依存関係の中にmusllinux向けの事前ビルド済みwheelが無いものがあった場合に
# ソースビルドへフォールバックできるよう最小限のビルドツールチェーンを入れる
# (このレイヤーはbuilderステージのみに存在し、最終イメージには含まれない)。
RUN apk add --no-cache gcc musl-dev libffi-dev openssl-dev

ENV UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build

# uv.lockが記録する相対パス依存を解決できるよう、リポジトリと同じ相対ディレクトリ
# 構造を再現してCOPYする(レイヤーキャッシュのため、依存関係マニフェスト類を
# アプリ本体より先にコピーする)。
COPY apps/persona_router/pyproject.toml apps/persona_router/uv.lock apps/persona_router/
COPY packages/shared_core packages/shared_core

WORKDIR /build/apps/persona_router

# --frozen: uv.lockと完全一致しない場合はビルドを失敗させる(ロック更新漏れの検知)。
# --no-install-project: apps/persona_router自体はpackage=false(配布用パッケージ
# ではないアプリケーション)のため、依存関係のみを/build/apps/persona_router/.venv
# へインストールする。
# --no-editable: apps/persona_router/pyproject.tomlの[tool.uv.sources]は
# nazokake-coreをeditable=trueで宣言している(ローカル開発用)。editable installは
# 絶対パス(/build/packages/shared_core/...)を指す.pthファイルしか作らないため、
# runtimeステージが.venvのみをCOPYする本構成だと`ModuleNotFoundError: No module
# named 'nazokake_core'`で起動時クラッシュする(apps/evaluator/Dockerfileで
# 実機確認済みの同一障害)。--no-editableでnazokake-coreを.venv内へ実ファイルとして
# 複製させ、runtimeステージが.venvだけで自己完結するようにする。
RUN uv sync --frozen --no-install-project --no-dev --no-editable


# ---- Runtime: 軽量な実行専用イメージ ----
FROM python:3.11-alpine AS runtime

# OSパッケージを最新のセキュリティパッチ状態にする。
RUN apk update && apk upgrade --no-cache

# apps/evaluator/Dockerfileと同一のCVE対策(setuptoolsのベンダリング版wheel/
# jaraco-contextの旧脆弱バージョンを、setuptools自体の更新で一掃する)。
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel jaraco-context

# 非rootユーザーで実行する。
RUN adduser -D -u 1000 appuser

WORKDIR /app

# uvが解決した仮想環境のみを取り込む(uv/pip/コンパイラ等のビルドツールチェーンは
# 含まれない)。builderと全く同じ絶対パスへコピーすることで、venv内スクリプトの
# shebangがこのコピー後も有効なまま解決できる。アプリ本体自体は/appに配置する。
COPY --from=builder /build/apps/persona_router/.venv /build/apps/persona_router/.venv

# アプリケーション本体を、必要なファイル/ディレクトリだけ個別にCOPYする
# (apps/persona_router/ を丸ごとCOPYしない設計。上記ヘッダー参照)。
COPY apps/persona_router/main.py apps/persona_router/env.py ./
COPY apps/persona_router/api ./api
COPY apps/persona_router/models ./models
COPY apps/persona_router/services ./services

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/build/apps/persona_router/.venv/bin:${PATH}"

# persona_routerはLocal-First前提を採用しない状態を持たないサービス(main.pyの
# docstring参照。ローカルSQLite等を一切使わないため、apps/evaluator/Dockerfileに
# あるような書き込み可能ディレクトリの追加設定は不要)。

USER appuser

EXPOSE 8080

# Cloud RunはPORT環境変数でリッスンポートを指定する(未設定時は8080にフォールバック)
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}

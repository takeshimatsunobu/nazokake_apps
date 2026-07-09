# syntax=docker/dockerfile:1
#
# なぞかけディスカバリー API (apps/evaluator/backend/main.py) 用イメージ。
# ビルドコンテキストはリポジトリルートを想定する(cloudbuild.yaml / Cloud Buildの
# 標準的な挙動に合わせるため)。
#
#   docker build -f apps/evaluator/Dockerfile -t nazo-agent-api .
#
# (Cloud Build の docker builder は BuildKit の --build-context をサポートしない
#  ため、素直な COPY で nazokake_core (packages/shared_core、リポジトリルート直下)
#  を取り込む。backend/ 各所はこれを `pip install -e` で参照しているが、これは
#  開発環境限定のパス依存であり、コンテナ内では実体をコピーして通常インストール
#  し直す必要がある。)
#
# セキュリティ上の理由から、apps/evaluator/ 直下の .env・serviceAccountKey.json・
# .venv_ai・data(データセット)・models(LoRA成果物)・frontend 等は
# COPYの対象を apps/evaluator/backend/ のみに限定することで構造的に一切イメージへ
# 含めない(機密情報はビルド時に埋め込まず、実行時に環境変数/シークレットマウントで
# 注入する)。apps/evaluator/.dockerignore はビルドコンテキストがリポジトリルートの
# 場合Dockerには自動適用されない(Docker/BuildKitが.dockerignoreを探すのはコンテキスト
# ルート、またはDockerfileと同名の<Dockerfile>.dockerignore)。ただし上記の
# 限定COPYにより、機密ファイルの混入防止自体はこの挙動に依存しない。

# ---- Builder: 依存関係の解決のみを行う(最終イメージにビルドツールを残さない) ----
FROM python:3.11-slim AS builder

WORKDIR /build

# 依存関係マニフェストのみを先にコピーし、レイヤーキャッシュを効かせる
COPY apps/evaluator/backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# nazokake_core をリポジトリルート(ビルドコンテキスト)から直接コピーし、
# 通常インストールする(editable installではなく、コンテナ内で完結するインストール)
COPY packages/shared_core ./shared_core
RUN pip install --no-cache-dir --prefix=/install ./shared_core


# ---- Runtime: 軽量な実行専用イメージ ----
FROM python:3.11-slim AS runtime

# 非rootユーザーで実行する
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

# ビルド済み依存関係のみを取り込む(pip/コンパイラ等のビルドツールチェーンは含まれない)
COPY --from=builder /install /usr/local

# アプリケーション本体(apps/evaluator/backend/)のみをコピーする(apps/evaluator直下の
# 秘密情報・大容量ファイルはCOPY対象に含まれないため構造的に混入し得ない)
COPY apps/evaluator/backend/ ./

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

USER appuser

EXPOSE 8080

# Cloud RunはPORT環境変数でリッスンポートを指定する(未設定時は8080にフォールバック)
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}

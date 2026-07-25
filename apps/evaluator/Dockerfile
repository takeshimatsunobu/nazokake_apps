# syntax=docker/dockerfile:1
#
# なぞかけディスカバリー API (apps/evaluator/backend/main.py) 用イメージ。
# ビルドコンテキストはリポジトリルートを想定する(cloudbuild.yaml / Cloud Buildの
# 標準的な挙動に合わせるため)。
#
#   docker build -f apps/evaluator/Dockerfile -t nazo-agent-api .
#
# 【instructions/218: uvによる決定論的ビルドの確立】以前はrequirements.txtを
# バージョン指定無しで`pip install -r`していたため、ビルドのたびに異なる依存関係
# グラフへ解決される可能性があった(非決定論的ビルド)。apps/evaluator/backend/に
# uv管理のpyproject.toml/uv.lock(Git管理対象、`uv lock`で生成・更新)を導入し、
# `uv sync --frozen`のみでインストールする。--frozenはuv.lockと依存関係の定義が
# 完全一致しない場合にビルド自体を失敗させるため、「ロックファイルの更新漏れ」が
# 決定論性を静かに破ることを構造的に防ぐ。
#
# nazokake_core(packages/shared_core)は、uv.lockが記録する相対パス依存
# (`{ path = "../../../packages/shared_core" }`、apps/evaluator/backend/pyproject.toml
# 基準)を解決できるよう、pyproject.tomlを/app直下に置き、3階層上(=ルート)基準で
# packages/shared_coreをコンテナのルート直下(/packages/shared_core)にCOPYする。
#
# 【instructions/224で判明した教訓】以前はbuilderステージのWORKDIRを/build配下の
# 深い階層(/build/apps/evaluator/backend)にしていたため、そこで`uv sync`が作る
# .venv内の各スクリプト(bin/uvicorn等)のshebangが絶対パス
# (#!/build/apps/evaluator/backend/.venv/bin/python)で焼き込まれていた。
# venvはPython venvの仕様上リロケータブルではないため、runtimeステージで
# COPY --from=builderにより別の絶対パス(/app/.venv)へ配置すると、shebangが
# 指す実行ファイルが存在せず`uvicorn: not found`(exit 127)でコンテナ起動に
# 失敗する。これは初回の実デプロイ試行(instructions/220-224のE2E検証)で
# 初めて到達したステップであり、Alpine移行以前から存在した潜在バグ。
# 対策として、builderステージでも.venvを最終的な配置先と同じ絶対パス
# (/app/.venv)に直接作成し、shebangが両ステージで有効であり続けるようにする。
#
# セキュリティ上の理由から、apps/evaluator/ 直下の .env・.venv_ai・data(データセット)・
# models(LoRA成果物)・frontend 等はCOPYの対象を apps/evaluator/backend/ のみに限定
# することで一切イメージへ含めない(機密情報はビルド時に埋め込まず、実行時に環境変数/
# シークレットマウントで注入する)。加えて、apps/evaluator/backend/ 配下に開発者の
# ローカル環境限定でserviceAccountKey.json等の機密ファイルが実在し得ることを
# instructions/218で確認した(限定COPYだけではこのケースを構造的に防げない)ため、
# 最終COPYへ `--exclude` を明示し、かつリポジトリルート直下に.dockerignore
# (Docker/BuildKitがビルドコンテキスト=リポジトリルートの場合に実際に読む場所)を
# 新設して二重に防止する(apps/evaluator/.dockerignoreはこのビルド構成では
# Dockerに読まれないため、実効性のある除外はこの2点に一本化した)。

# ---- Builder: uvでロックファイル通りに依存関係を解決する(最終イメージにuv/ビルド
#      ツールを残さない) ----
# instructions/224: python:3.11-slim(Debian)のperl-base/libattr1/libacl1が
# CVE未パッチ(FIXED_VERSION空欄)かつperl/attr/aclという名前でのpurgeが
# 効かない(essentialパッケージ/共有ライブラリで単純削除不可)ことが実機CIで
# 判明したため、Attack Surfaceごと排除する目的でmusl/Alpineベースへ移行する。
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

WORKDIR /app

# uv.lockが記録する相対パス依存(pyproject.toml基準で3階層上=ルート)を解決できる
# よう、packages/shared_coreはコンテナのルート直下に配置する(レイヤーキャッシュの
# ため、依存関係マニフェスト類をアプリ本体より先にコピーする)。
COPY apps/evaluator/backend/pyproject.toml apps/evaluator/backend/uv.lock ./
COPY packages/shared_core /packages/shared_core

# --frozen: uv.lockと完全一致しない場合はビルドを失敗させる(ロック更新漏れの検知)。
# --no-install-project: apps/evaluator/backend自体はpackage=false(配布用パッケージ
# ではないアプリケーション)のため、依存関係のみを/app/.venvへインストールする。
# ここで.venvを最終配置先と同じ絶対パス(/app/.venv)に直接作ることで、
# venv内スクリプトのshebangがruntimeステージへコピーした後も有効なままになる
# (上記ヘッダーコメント参照)。
RUN uv sync --frozen --no-install-project --no-dev


# ---- Runtime: 軽量な実行専用イメージ ----
# instructions/224: python:3.11-slim(Debian)のperl-base/libattr1/libacl1の
# CVE(未パッチ、purgeも不可)を解消するためAlpineへ移行。Alpineの最小イメージには
# そもそもperl/attr/acl相当のパッケージが標準で入っていない(Attack Surfaceの
# 縮小そのもの)。
FROM python:3.11-alpine AS runtime

# OSパッケージを最新のセキュリティパッチ状態にする。
RUN apk update && apk upgrade --no-cache

# instructions/224フォローアップ: CIのデバッグ実行(実機ファクト)で判明した通り、
# 単純な`pip install --upgrade wheel jaraco-context`はトップレベルの新規インストール
# を作るだけで、setuptoolsが内部に同梱するベンダリング版(setuptools/_vendor/
# wheel-0.45.1, jaraco.context-5.3.0、いずれも旧脆弱バージョン)には届かない。
# setuptools自体を最新へ上げることで、そのベンダリング内容ごと更新する。
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel jaraco-context

# 非rootユーザーで実行する(busybox adduserはAlpine標準、-Dでパスワード未設定、
# ホームディレクトリはデフォルトで作成される)。
RUN adduser -D -u 1000 appuser

WORKDIR /app

# uvが解決した仮想環境のみを取り込む(uv/pip/コンパイラ等のビルドツールチェーンは
# 含まれない)。builderステージでも同じ絶対パス(/app/.venv)に作成しているため、
# venv内スクリプトのshebang(例: bin/uvicornの#!/app/.venv/bin/python)が
# このコピー後も有効なまま解決できる。
COPY --from=builder /app/.venv /app/.venv

# アプリケーション本体(apps/evaluator/backend/)のみをコピーする。--excludeにより、
# 開発者のローカル環境限定で存在し得る機密ファイルが万一このディレクトリ配下にあっても
# 構造的にイメージへ含めない(上記ヘッダー参照)。
COPY --exclude=serviceAccountKey.json --exclude=.env --exclude=.env.* \
    apps/evaluator/backend/ ./

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:${PATH}"

USER appuser

EXPOSE 8080

# Cloud RunはPORT環境変数でリッスンポートを指定する(未設定時は8080にフォールバック)
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}

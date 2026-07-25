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
# 基準)をコンテナ内でも解決できるよう、リポジトリと同じ相対ディレクトリ構造
# (/build/apps/evaluator/backend, /build/packages/shared_core)を再現してCOPYする。
# (uvは`../../../`のようなbase directoryを越える相対パス正規化を明示的に拒否する
# ため、この3階層ぶんのディレクトリ構造は浅くできない -- instructions/224で
# /appへ平坦化しようとして`cannot normalize a relative path beyond the base
# directory`で実際にビルド失敗したことを確認済み。)
#
# 【instructions/224で判明した教訓】.venv内の各スクリプト(bin/uvicorn等)の
# shebangは、`uv sync`実行時のカレントディレクトリを起点とした絶対パス
# (#!/build/apps/evaluator/backend/.venv/bin/python)で焼き込まれる。venvは
# Python venvの仕様上リロケータブルではないため、runtimeステージで
# COPY --from=builderにより別の絶対パス(/app/.venv等)へ配置すると、shebangが
# 指す実行ファイルが存在せず`uvicorn: not found`(exit 127)でコンテナ起動に
# 失敗する。これは初回の実デプロイ試行(instructions/220-224のE2E検証)で
# 初めて到達したステップであり、Alpine移行以前から存在した潜在バグ。
# 対策として、runtimeステージでも.venvをbuilderと全く同じ絶対パス
# (/build/apps/evaluator/backend/.venv)へCOPYし、shebangを両ステージで有効な
# ままにする(実行時のアプリ本体自体は引き続き/appに配置し、PATHで
# /build/apps/evaluator/backend/.venv/binを指す)。ビルドツールチェーン
# (gcc等、builderステージのみでapk addしたもの)は.venv配下には存在しないため、
# このディレクトリをコピーしても最終イメージにビルドツールは混入しない。
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

WORKDIR /build

# uv.lockが記録する相対パス依存を解決できるよう、リポジトリと同じ相対ディレクトリ
# 構造を再現してCOPYする(レイヤーキャッシュのため、依存関係マニフェスト類を
# アプリ本体より先にコピーする)。
COPY apps/evaluator/backend/pyproject.toml apps/evaluator/backend/uv.lock apps/evaluator/backend/
COPY packages/shared_core packages/shared_core

WORKDIR /build/apps/evaluator/backend

# --frozen: uv.lockと完全一致しない場合はビルドを失敗させる(ロック更新漏れの検知)。
# --no-install-project: apps/evaluator/backend自体はpackage=false(配布用パッケージ
# ではないアプリケーション)のため、依存関係のみを/build/apps/evaluator/backend/.venv
# へインストールする(runtimeステージでも同じ絶対パスへコピーする、上記ヘッダー
# コメント参照)。
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
# 含まれない)。builderと全く同じ絶対パスへコピーすることで、venv内スクリプトの
# shebang(例: bin/uvicornの#!/build/apps/evaluator/backend/.venv/bin/python)が
# このコピー後も有効なまま解決できる(上記ヘッダーコメント参照)。アプリ本体自体は
# 引き続き/appに配置する。
COPY --from=builder /build/apps/evaluator/backend/.venv /build/apps/evaluator/backend/.venv

# アプリケーション本体(apps/evaluator/backend/)のみをコピーする。--excludeにより、
# 開発者のローカル環境限定で存在し得る機密ファイルが万一このディレクトリ配下にあっても
# 構造的にイメージへ含めない(上記ヘッダー参照)。
COPY --exclude=serviceAccountKey.json --exclude=.env --exclude=.env.* \
    apps/evaluator/backend/ ./

# instructions/224: main.pyはimport時に(1) apps.tactical_cic.webhook_api、
# (2) StaticFiles用の <root>/public、(3) apps/evaluator/frontend/public を
# 要求する(いずれもビルド未対応で初回の実デプロイ試行時にクラッシュを確認済み)。
# StaticFilesはコンストラクタ時点でディレクトリ存在をチェックするため、
# 欠けているとuvicorn起動前にRuntimeError/ModuleNotFoundErrorで即クラッシュする。
# いずれもGit管理下の静的ファイル(ビルドステップ不要)のため、そのままCOPYする。
COPY apps/tactical_cic ./apps/tactical_cic
COPY public ./public
COPY apps/evaluator/frontend/public ./apps/evaluator/frontend/public

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PROJECT_ROOT=/app \
    PATH="/build/apps/evaluator/backend/.venv/bin:${PATH}"

USER appuser

EXPOSE 8080

# Cloud RunはPORT環境変数でリッスンポートを指定する(未設定時は8080にフォールバック)
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}

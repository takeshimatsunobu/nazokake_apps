# syntax=docker/dockerfile:1
# infra/verification_env/mlops_scheduler.Dockerfile
# ====================================================
# mlops-scheduler(MLOps自動起動トリガーのサイドカー)実行環境(instructions/161)。
#
# 【Step 1: .venvマウントの廃止とロックファイルによる決定論的ビルド】
# ホストの.venvをそのままマウントする設計(instructions/160)は、ホスト側で場当たり的に
# 行われたpip install/uv syncの結果にイメージの中身が暗黙に依存してしまい、ホストと
# コンテナ間で構成がドリフトする(「動いていた設定」が再現できなくなる)アンチパターン
# だったため撤回する。代わりに、このリポジトリに既存する依存関係マニフェスト
# (requirements_orchestrator.txt、packages/shared_core/pyproject.toml)だけを根拠に、
# イメージビルド時に.venvを一から決定論的に構築する。
#
# Build from repo root:
#   docker compose -f infra/verification_env/docker-compose.yml build mlops-scheduler

FROM python:3.11-slim

# tools/mlops_trigger.py -> tools/mlops_pipeline_agent.py/nazo.py、tools/agent_graph.py
# ._run_benchmark_summary()等の既存コード(このDockerfileでは無改変)がサブプロセスで
# `uv run python ...`を呼び出す構造のため、uvバイナリ自体もイメージへ導入する。
# curl|shではなく、astral公式が配布する「uvバイナリのみを含む」distrolessイメージから
# のマルチステージCOPYを用いることで、ビルド時の外部ダウンロードスクリプト実行を避け、
# バージョンをこの1行のタグで厳密に固定する(決定論的ビルド)。
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /usr/local/bin/

# tools/benchmark/run_benchmark.pyがDocker-outside-of-Dockerで`docker run`を起動する
# ためのCLI自体をビルド時に導入する(コンテナ起動ごとのapt-getは、実行タイミングに
# よってインストール内容が変わりうるドリフトの余地を生むため、イメージビルド時に
# 一度だけ固定する)。
RUN apt-get update && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# 【決定論的インストール】requirements_orchestrator.txt(tools/*.pyのオーケストレーター
# 層全体の既存の依存関係マニフェスト)と、packages/shared_core(nazokake_core、
# tools/extract_dataset.py等が依存するドメイン層、自身のpyproject.tomlを持つ)を、
# それぞれの既存の宣言だけを根拠にインストールする。アプリケーションコード本体を
# COPYする前に依存関係だけを先にCOPY・インストールすることで、依存関係が変わらない
# 限りDockerのレイヤーキャッシュが効き、ソースコードの変更のみで毎回フルの
# 再インストールが走らないようにする。
COPY requirements_orchestrator.txt .
COPY packages/shared_core packages/shared_core
RUN uv venv .venv \
    && uv pip install --python .venv/bin/python -r requirements_orchestrator.txt \
    && uv pip install --python .venv/bin/python ./packages/shared_core

# アプリケーションコード本体(tools/*.py)をCOPYする。ホストへの書き込み権限は
# 一切要求しない(イミュータブルなイメージとして扱う、コンテナネイティブ原則)。
#
# 【既知の限界】このイメージはホストのソースツリーをコンテナ内の別パス(/workspace)へ
# 焼き込むため、tools/benchmark/run_benchmark.pyがこのコンテナ内からDocker-outside-of-
# Docker経由でサンドボックスコンテナへ渡す`-v {BASE_DIR}/...:...:ro`系の引数は、
# ホストのdockerdにとって(mlops-schedulerコンテナ内のパスではなく)ホスト自身の
# 実パスとして解釈される。この経路(ベンチマークのfixture/tools/packages/apps読み取り
# 専用マウント)を実際にこのサイドカーから起動する場合は、ホストの実パスと一致する
# 場所へ明示的にバインドマウントする追加対応が別途必要であり、本チケット
# (instructions/161: .venvマウント廃止/ネットワーク隔離/PID1問題/耐障害性)の
# スコープ外として意図的に対応していない。
COPY tools/ tools/

ENV PATH="/workspace/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 【Step 3: PID 1問題の解消】ENTRYPOINTはbashの無限sleepループではなく、signalモジュール
# でSIGTERM/SIGINTを直接トラップするtools/scheduler_daemon.py。execフォーム([...])を
# 用いる(シェル経由の文字列フォームだとシェル自身がPID 1になり、同じPID 1問題を
# 再導入してしまうため)。
ENTRYPOINT ["python", "tools/scheduler_daemon.py"]

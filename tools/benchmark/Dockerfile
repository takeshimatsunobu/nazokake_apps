# syntax=docker/dockerfile:1
# Nazo-Agentベンチマーク用サンドボックス。ホストのLLM推論(Ollama/Qwen)からは完全に
# 分離し、「AST置換の適用」と「Pytest実行」のみをこのコンテナ内で行う。
# tools/, packages/, apps/ はビルド時にCOPYしない。docker run側で -v ...:ro として
# 読み取り専用マウントする想定(ホストのソースをイメージへ焼き込まない)。
#
# Build from repo root: docker build -f tools/benchmark/Dockerfile -t nazo-benchmark-sandbox .
FROM python:3.11-slim

RUN useradd --create-home --uid 1000 sandboxuser

# gosu: 特権降格(root起動→非特権ユーザーへのexec切り替え)専用ツール。sudo等と異なり
# 余分なプロセスを残さずexecで完全に置き換わるため、シグナル伝播やゾンビプロセスの問題を
# 起こさない(instructions/153: 最小特権原則をENTRYPOINTパターンで維持する)。
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY tools/benchmark/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/benchmark/container_runner.py .
COPY tools/benchmark/entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

# /workspace, /output はランタイムの書き込み対象(fixture/tools/packages/apps は
# 常にroマウント)。ビルド時にも作成・chownしておくが、実際の権限不整合はランタイムの
# ホスト側マウントによって生じるため、最終的な権限調整はentrypoint.sh(root起動時の
# chown -R)で行う。
RUN mkdir -p /workspace /output && chown -R sandboxuser:sandboxuser /workspace /output

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# 【絶対制約】USER指定は行わない(デフォルトのroot起動)。root権限はentrypoint.sh内の
# chown -R実行にのみ使用し、その直後にgosuでsandboxuserへ降格してからcontainer_runner.py
# を実行する(最小特権原則。rootでアプリケーションロジック自体を実行することはない)。
ENTRYPOINT ["/app/entrypoint.sh"]

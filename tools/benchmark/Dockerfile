# syntax=docker/dockerfile:1
# Nazo-Agentベンチマーク用サンドボックス。ホストのLLM推論(Ollama/Qwen)からは完全に
# 分離し、「AST置換の適用」と「Pytest実行」のみをこのコンテナ内で行う。
# tools/, packages/, apps/ はビルド時にCOPYしない。docker run側で -v ...:ro として
# 読み取り専用マウントする想定(ホストのソースをイメージへ焼き込まない)。
#
# Build from repo root: docker build -f tools/benchmark/Dockerfile -t nazo-benchmark-sandbox .
FROM python:3.11-slim

RUN useradd --create-home --uid 1000 sandboxuser

WORKDIR /app
COPY tools/benchmark/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/benchmark/container_runner.py .

# /workspace, /output はランタイムの書き込み対象(fixture/tools/packages/apps は
# 常にroマウント)。非rootユーザーが書き込めるようビルド時にchownしておく。
RUN mkdir -p /workspace /output && chown -R sandboxuser:sandboxuser /workspace /output

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

USER sandboxuser

ENTRYPOINT ["python", "/app/container_runner.py"]

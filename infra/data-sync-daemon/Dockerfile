# syntax=docker/dockerfile:1
#
# Firestore<->ローカルSQLite バッチ同期用イメージ(instructions/001、
# SSoT_architecture.md 8.2節)。data/sqlite/ と data/credentials/ を
# 実行時にマウントし、非rootユーザーで稼働させる(WALモードのファイル権限を
# ホスト側と一致させ、排他制御を破壊しないため)。
#
# Build from repo root: docker build -f infra/data-sync-daemon/Dockerfile -t nazo-data-sync-daemon .
FROM python:3.11-slim

RUN useradd --create-home --uid 1000 syncuser

WORKDIR /app

COPY requirements_orchestrator.txt .
RUN pip install --no-cache-dir -r requirements_orchestrator.txt

# packages/shared_core (NazokakeItem等のPydanticスキーマ、SSoT 8.2節) を
# 通常インストールする(editable installではなく、コンテナ内で完結させる)。
COPY packages/shared_core ./shared_core
RUN pip install --no-cache-dir ./shared_core

COPY infra/data-sync-daemon/sync_daemon_entrypoint.py .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN chown -R syncuser:syncuser /app

USER syncuser

CMD ["python", "sync_daemon_entrypoint.py"]

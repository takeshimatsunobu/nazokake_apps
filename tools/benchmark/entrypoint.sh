#!/usr/bin/env bash
# tools/benchmark/entrypoint.sh
# ================================
# サンドボックスコンテナのENTRYPOINT。最小特権原則を維持したまま、実行時にマウントされる
# /output・/workspace の権限不整合(ホスト側のUID/GIDとイメージビルド時のsandboxuser
# (UID 1000)が一致しない問題、instructions/148-152)を解決する特権降格パターン
# (gosu)。
#
# コンテナ自身はroot起動(Dockerfileのデフォルト、USER指定なし)だが、この
# entrypoint.sh以外のロジック(container_runner.py本体)は一切rootで実行しない:
#   1. rootとしてマウント領域の所有権をsandboxuserへ揃える(chown -R)。
#   2. gosuでsandboxuserへ即座に権限を降格し、実際のアプリケーションロジック
#      (container_runner.py)はここから先、非特権ユーザーとしてのみ実行される。

set -euo pipefail

chown -R sandboxuser:sandboxuser /output /workspace

exec gosu sandboxuser python /app/container_runner.py "$@"

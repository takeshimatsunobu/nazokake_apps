#!/usr/bin/env bash
# infra/verification_env/deploy_pull.sh
# =========================================
# 検証サーバー(GCP VM)側のPull型デプロイスクリプト(instructions/187)。
#
# 【背景】従来のtools/deploy/run_verification_server.ps1は、Windows側でgit archiveした
# HEADスナップショットをZIP化しgcloud compute scpで転送、リモートでunzip -oするだけの
# ClickOps運用だった。この方式はVM上の稼働ディレクトリ(~/nazokake_apps)から.git履歴を
# 物理的に喪失させる(unzipはただのファイル置き換えであり、コミット履歴を一切保持しない)。
# Nazo-Agentの自律エスカレーション(tools/agent_graph.py)が過去のコミットハッシュとの差分
# を評価し自律的にロールバック(自己修復)する前提を、この履歴喪失が構造的に破壊していた。
#
# 【是正】VM上に恒久的なBareリポジトリ(~/nazokake_apps.git)を稼働ディレクトリとは別に
# 保持し、これを稼働ディレクトリ(~/nazokake_apps)からの唯一のfetch元(origin、SSoT)と
# 見なす。ローカル(Windows)からのgit push(tools/deploy/deploy_to_vm.ps1)を受けた後、
# このスクリプトが git fetch + git reset --hard で稼働ディレクトリを決定論的に同期する
# ことで、稼働ディレクトリの.git履歴を常に保持したままデプロイできる(Pull型)。
#
# 使い方(検証サーバー上、通常はtools/deploy/deploy_to_vm.ps1からSSH経由で非同期に
# キックされる。手動実行も可):
#   bash infra/verification_env/deploy_pull.sh
#
# 【決定論的な同期対象】git push側(tools/deploy/deploy_to_vm.ps1)は常に固定のブランチ
# 名 DEPLOY_BRANCH(既定"deploy")へforce pushする。ローカルの作業ブランチ名(例:
# test/agent-benchmark)がなんであっても、デプロイ対象は常にこの1本のブランチに
# 一意化されるため、「どのブランチを同期すべきか」という曖昧さを構造的に排除する。

set -euo pipefail

VERIFICATION_HOME="${VERIFICATION_HOME:-${HOME}}"
REPO_DIR="${REPO_DIR:-${VERIFICATION_HOME}/nazokake_apps}"
BARE_REPO_DIR="${BARE_REPO_DIR:-${VERIFICATION_HOME}/nazokake_apps.git}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-deploy}"

echo "=== [1/3] Bareリポジトリからの稼働ディレクトリ同期(Pull) ==="

if [[ ! -d "${BARE_REPO_DIR}" ]]; then
    echo "🚨 [Fail-Closed] Bareリポジトリが見つかりません: ${BARE_REPO_DIR}" >&2
    echo "   先にtools/deploy/deploy_to_vm.ps1でgit init --bareを実行してください。" >&2
    exit 1
fi

if [[ ! -d "${REPO_DIR}/.git" ]]; then
    echo "ℹ️  ${REPO_DIR} が未クローンのため、Bareリポジトリから初回クローンします。"
    git clone "${BARE_REPO_DIR}" "${REPO_DIR}"
fi

cd "${REPO_DIR}"

# 【決定論的なorigin固定】既存チェックアウトのorigin URLが何らかの理由でズレていても、
# 常にこのVM自身のBareリポジトリを指すよう明示的に上書きする(暗黙のリモート設定への
# 依存を排除する)。
if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "${BARE_REPO_DIR}"
else
    git remote add origin "${BARE_REPO_DIR}"
fi

echo "🔄 git fetch origin ${DEPLOY_BRANCH} ..."
git fetch origin "${DEPLOY_BRANCH}"

# 【絶対制約】git clean等の未追跡ファイル削除は一切行わない。data/・run/配下の
# 永続層(SQLite DB)・揮発層(VRAMロック)は元々.gitignore対象(非追跡)のため、
# reset --hardの対象外(reset --hardは追跡済みファイルの内容のみを書き換える)。
echo "♻️  git reset --hard origin/${DEPLOY_BRANCH} ..."
git reset --hard "origin/${DEPLOY_BRANCH}"
echo "✅ 稼働ディレクトリを $(git rev-parse --short HEAD) へ同期しました。"

echo "=== [2/3] setup_verification_env.sh(初回のみ、冪等性センチナル) ==="
# 【冪等性(instructions/165を継承)】OSレベルのプロビジョニング(cgroup委譲・NVIDIA
# Container Toolkit登録)は1度で十分であり、繰り返しdockerdを再起動するリスクそのものを
# 構造的に無くすため、センチナルファイルにより初回のみ実行する。
PROVISION_MARKER="${VERIFICATION_HOME}/.nazokake_verification_env_provisioned"
if [[ ! -f "${PROVISION_MARKER}" ]]; then
    sudo bash infra/verification_env/setup_verification_env.sh
    touch "${PROVISION_MARKER}"
else
    echo "ℹ️  setup_verification_env.sh は既に適用済みのためスキップします(冪等性)。"
fi

echo "=== [3/3] mlops-schedulerサイドカーの再起動 ==="
# docker compose up --buildはVM状態に関わらず毎回実行する(コードの再デプロイ自体は
# 毎回反映させる必要があり、Compose自体は冪等かつtools/scheduler_daemon.pyの
# Graceful Shutdown対応済みのため安全、instructions/165と同じ方針)。
docker compose -f infra/verification_env/docker-compose.yml up -d --build mlops-scheduler

echo "🎉 [deploy_pull] Pull型デプロイが完了しました($(git rev-parse --short HEAD))。"

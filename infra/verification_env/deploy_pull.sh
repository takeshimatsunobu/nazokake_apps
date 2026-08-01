#!/usr/bin/env bash
# infra/verification_env/deploy_pull.sh
# =========================================
# 検証サーバー(GCP VM)側のPull型デプロイスクリプト
# (instructions/187、instructions/299でVM内Bareリポジトリの中継を完全に廃止、
# instructions/300でsystemd user unit(nazokake-deploy.service)経由の起動へ移行)。
#
# 【背景】従来のtools/deploy/run_verification_server.ps1は、Windows側でgit archiveした
# HEADスナップショットをZIP化しgcloud compute scpで転送、リモートでunzip -oするだけの
# ClickOps運用だった。この方式はVM上の稼働ディレクトリ(~/nazokake_apps)から.git履歴を
# 物理的に喪失させる(unzipはただのファイル置き換えであり、コミット履歴を一切保持しない)。
# Nazo-Agentの自律エスカレーション(tools/agent_graph.py)が過去のコミットハッシュとの差分
# を評価し自律的にロールバック(自己修復)する前提を、この履歴喪失が構造的に破壊していた。
#
# 【instructions/187での是正、instructions/299での再是正】instructions/187では、VM上に
# 恒久的なBareリポジトリ(~/nazokake_apps.git)を稼働ディレクトリとは別に保持し、
# ローカル(Windows)からのgit push --force(tools/deploy/deploy_to_vm.ps1)をそこで
# 中継してから、このスクリプトがそのBareリポジトリをfetch元とすることで.git履歴を
# 失わずにデプロイする設計にしていた。しかし実運用でIAPトンネル経由の大容量push
# (帯域制約)がBroken pipeで失敗する事象が頻発したため、instructions/299でこの
# 中継地点(Bareリポジトリ)自体を完全に廃止した。稼働ディレクトリ(~/nazokake_apps)は
# GitHub(SSoT)を唯一のfetch元とし、直接 `git fetch origin` + `git reset --hard
# origin/main` で決定論的に同期する。tools/deploy/deploy_to_vm.ps1側は「VM起動→
# SSH開通確認→このスクリプトの非同期キック」のみに純化され、git push自体を一切
# 行わなくなった(instructions/270のPRベース運用と合わせ、デプロイはGitHub main への
# マージ後にこのスクリプトを呼ぶだけで完結する)。
#
# 使い方(検証サーバー上、通常はtools/deploy/deploy_to_vm.ps1からSSH経由で
# `systemctl --user start --no-block nazokake-deploy.service`としてキックされる
# (instructions/300、このファイル自体がnazokake-deploy.serviceのExecStart)。
# 手動実行も可:
#   bash infra/verification_env/deploy_pull.sh

set -euo pipefail

VERIFICATION_HOME="${VERIFICATION_HOME:-${HOME}}"
REPO_DIR="${REPO_DIR:-${VERIFICATION_HOME}/nazokake_apps}"
# 【instructions/299】VM内のBareリポジトリではなく、GitHub本体を唯一のfetch元とする。
GITHUB_REPO_URL="${GITHUB_REPO_URL:-https://github.com/takeshimatsunobu/nazokake_apps.git}"
DEPLOY_TARGET_BRANCH="${DEPLOY_TARGET_BRANCH:-main}"
AUTO_SHUTDOWN_DEST="${AUTO_SHUTDOWN_DEST:-/home/takes/nazokake-evaluator/scripts/auto_shutdown.py}"

# 【/tmp名前空間の共有検証(instructions/200)】本スクリプトはgcloud compute sshで
# キックされるプレーンなログインシェル、auto_shutdown.py側はtakesユーザーの
# crontabから直接起動される。どちらもsystemdサービス化やコンテナ化はされておらず
# (docker composeでコンテナ化されているのはmlops-schedulerサイドカーのみで、本
# スクリプト自身はホストのベアメタルシェルで実行される)、PrivateTmp等による
# /tmpの名前空間分離を受けない。したがって両者はホストOSのグローバルな/tmpを
# 確実に共有でき、ロックファイルパスを/tmp外へ変更する必要はない。
DEPLOY_LOCK_FILE="${DEPLOY_LOCK_FILE:-/tmp/deployment_in_progress.lock}"

# 【原子的排他制御(instructions/199)】touch/rmによる存在チェックは、プロセスが
# SIGKILL等で異常終了した際にロックファイルだけが残置される(=監視スクリプト側の
# 安全装置を無期限に無力化しうる)非決定的な設計だった。exec {fd}>file + flockに
# よるファイル記述子ロックへ置き換えることで、本スクリプトがどのように終了しても
# (正常終了・SIGKILL問わず)OSがfd close時に確実にロックを解放する設計とする。
exec {DEPLOY_LOCK_FD}>"${DEPLOY_LOCK_FILE}"
if ! flock -n "${DEPLOY_LOCK_FD}"; then
    echo "🚨 [Fail-Closed] 他のデプロイが既に進行中です(ロック取得失敗: ${DEPLOY_LOCK_FILE})。" >&2
    exit 1
fi

echo "=== [1/6] GitHubからの稼働ディレクトリ同期(Pull、instructions/299) ==="

if [[ ! -d "${REPO_DIR}/.git" ]]; then
    echo "ℹ️  ${REPO_DIR} が未クローンのため、GitHubから初回クローンします。"
    git clone "${GITHUB_REPO_URL}" "${REPO_DIR}"
fi

cd "${REPO_DIR}"

# 【決定論的なorigin固定】既存チェックアウトのorigin URLが何らかの理由でズレていても
# (旧Bareリポジトリを指したまま等)、常にGitHub本体を指すよう明示的に上書きする
# (暗黙のリモート設定への依存を排除する、instructions/187由来の設計方針を踏襲)。
if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "${GITHUB_REPO_URL}"
else
    git remote add origin "${GITHUB_REPO_URL}"
fi

echo "🔄 git fetch origin ..."
git fetch origin

# 【絶対制約】git clean等の未追跡ファイル削除は一切行わない。data/・run/配下の
# 永続層(SQLite DB)・揮発層(VRAMロック)は元々.gitignore対象(非追跡)のため、
# reset --hardの対象外(reset --hardは追跡済みファイルの内容のみを書き換える)。
echo "♻️  git reset --hard origin/${DEPLOY_TARGET_BRANCH} ..."
git reset --hard "origin/${DEPLOY_TARGET_BRANCH}"
echo "✅ 稼働ディレクトリを $(git rev-parse --short HEAD) へ同期しました。"

echo "=== [2/6] auto_shutdown.pyをCron参照パスへ同期 ==="
# 【IaCとランタイムの構成同期(instructions/200)】instructions/199でauto_shutdown.py
# をリポジトリ管理下に置きflockによる排他制御を実装したが、本スクリプトは
# git reset --hardでREPO_DIR配下を更新するのみで、実際にtakesユーザーのcrontabが
# 参照するAUTO_SHUTDOWN_DESTへは配置していなかった(同期漏れ)。これを放置すると、
# デプロイのたびにリポジトリ側だけが更新され、VM上で稼働し続ける旧タイマー
# (mtimeベースの非決定的な監視ロジック)が発火し続ける「突然死」を招く。
# install -m 755はコピーと実行権限付与を1コマンドで行い、コピー漏れ・権限漏れの
# どちらも構造的に防ぐ。
mkdir -p "$(dirname "${AUTO_SHUTDOWN_DEST}")"
install -m 755 "${REPO_DIR}/infra/verification_env/scripts/auto_shutdown.py" "${AUTO_SHUTDOWN_DEST}"
echo "✅ ${AUTO_SHUTDOWN_DEST} を最新化しました。"

echo "=== [3/6] nazokake-deploy.serviceをsystemdユーザーユニットへ同期(instructions/300) ==="
# 【IaCとランタイムの構成同期】auto_shutdown.pyと全く同じ理由: git reset --hardは
# REPO_DIR配下を更新するのみで、systemdが実際に読むユニット探索パス
# (~/.config/systemd/user/)へは配置しない。ここで同期しないと、リポジトリ側の
# ユニット定義を更新しても次回デプロイ以降のsystemctl --user startに反映されない。
# 新規VM(deploy_pull.shが一度も走っていない)向けのフォールバックとして、
# infra/verification_env/startup-script.sh(VM起動時)も同じ同期を行う。
SYSTEMD_USER_UNIT_DIR="${SYSTEMD_USER_UNIT_DIR:-${VERIFICATION_HOME}/.config/systemd/user}"
mkdir -p "${SYSTEMD_USER_UNIT_DIR}"
install -m 644 "${REPO_DIR}/infra/verification_env/nazokake-deploy.service" \
    "${SYSTEMD_USER_UNIT_DIR}/nazokake-deploy.service"
# 【Fail-Open】本スクリプトを暫定的にsystemd経由以外(手動bash実行等)でキックした
# 場合、systemdユーザーマネージャのバスに接続できないことがある。この同期自体の
# 失敗でデプロイ本体(git同期・docker compose up)まで止めるべきではないため、
# 警告のみ出して継続する(instructions/212のFirestore記録と同じFail-Open方針)。
systemctl --user daemon-reload \
    || echo "⚠️  [WARN] systemctl --user daemon-reloadに失敗しました(systemdユーザーマネージャに未接続の可能性)。" >&2
echo "✅ ${SYSTEMD_USER_UNIT_DIR}/nazokake-deploy.service を最新化しました。"

echo "=== [4/6] setup_verification_env.sh(初回のみ、冪等性センチナル) ==="
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

echo "=== [5/6] mlops-schedulerサイドカーの再起動 ==="
# docker compose up --buildはVM状態に関わらず毎回実行する(コードの再デプロイ自体は
# 毎回反映させる必要があり、Compose自体は冪等かつtools/scheduler_daemon.pyの
# Graceful Shutdown対応済みのため安全、instructions/165と同じ方針)。
docker compose -f infra/verification_env/docker-compose.yml up -d --build mlops-scheduler

DEPLOYED_COMMIT="$(git rev-parse --short HEAD)"

echo "=== [6/6] デプロイ状態をFirestoreへ記録(instructions/212: SSH無しのDoD検証用) ==="
# 【絶対制約に抵触しない範囲でのFail-Open】ここでの失敗(firebase_admin未導入、
# サービスアカウント権限不足等)は、直前まで成功していたデプロイ自体を無効化すべき
# ではない(観測性の記録が、デプロイという実体のある成功を覆い隠してはならない)。
# そのため他のステップと異なりexit 1で全体を止めず、警告のみ出して継続する。
CONTAINER_STATUS_JSON="$(docker compose -f infra/verification_env/docker-compose.yml ps --format json 2>/dev/null || echo '[]')"
"${REPO_DIR}/.venv/bin/python" - "${DEPLOYED_COMMIT}" "${CONTAINER_STATUS_JSON}" <<'PYEOF' || echo "⚠️  [WARN] デプロイ状態のFirestore記録に失敗しました(デプロイ自体は完了済み)。" >&2
import json
import sys

sys.path.insert(0, "packages/shared_core")
from nazokake_core.deploy_status_sync import write_deploy_status

commit_hash, container_status_json = sys.argv[1], sys.argv[2]
try:
    containers = json.loads(container_status_json)
except json.JSONDecodeError:
    containers = {"raw": container_status_json}

write_deploy_status(
    instance_name="nazokake-l4-vm",
    commit_hash=commit_hash,
    status="deployed",
    message="docker compose up -d --build mlops-scheduler succeeded",
    containers={"mlops_scheduler": containers},
)
print(f"✅ デプロイ状態をFirestoreへ記録しました(commit={commit_hash})。")
PYEOF

echo "🎉 [deploy_pull] Pull型デプロイが完了しました(${DEPLOYED_COMMIT})。"

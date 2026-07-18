#!/usr/bin/env bash
# infra/verification_env/setup_verification_env.sh
# =====================================================
# Nazo-Agentベンチマーク(tools/benchmark/run_benchmark.py)を実行するための、
# Rootless Docker + NVIDIA GPU検証サーバーのプロビジョニングスクリプト(instructions/145/146)。
#
# 【設計方針】
# このスクリプトはOS/ホストレベルの前提条件(cgroup委譲・GPUランタイムフック)のみを
# 準備する。アトミックI/O・CQRS静的JSONダンプ・5次元/6次元評価ゲート・軽量ローカルRAG
# (Experience Replay)といったアプリケーション層のセキュア基盤は、このリポジトリを
# クローンして既存モジュール(tools/export_metrics.py, tools/benchmark/run_benchmark.py,
# tools/knowledge_retriever.py 等)をそのまま実行することで再現する(再実装・フォークは
# 一切行わない。実装の二重化によるドリフトを構造的に禁止する)。
#
# 【VRAM制限についての正直な技術的前提】
# Dockerネイティブにはコンテナごとのハード VRAM 量子化機構が無い(NVIDIA vGPU/MPS
# ライセンスが別途必要)。したがって「決定論的な強制」は以下の2点の組み合わせで実現する:
#   1. --gpus device=0 によるGPU単一専有(複数コンテナへの分割共有をそもそも許可しない)。
#   2. tools/config.py の VRAM_LOCK_PATH(filelock)による、アプリ本体・MLOpsパイプライン・
#      このベンチマーク検証の全プロセス間での直列化(既存の排他制御をそのまま再利用する)。
#
# 使い方(検証サーバー上でsudo権限を持つユーザーとして実行):
#   sudo bash infra/verification_env/setup_verification_env.sh
#
# このスクリプトは開発機(Windows、Docker未導入)では実行・検証できない。
# tests/verification_env/test_infra_behavior.py の test_cgroup_delegation_is_active /
# test_nvidia_toolkit_hook_and_gpu_visible は、このスクリプトを適用した検証サーバー上で
# 実行した場合にのみ(pytest.skipされずに)実際に合否を検証する。

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "🚨 このスクリプトはsudo権限が必要です(systemd/NVIDIA Container Toolkitの設定を書き込むため)。" >&2
    echo "   例: sudo bash infra/verification_env/setup_verification_env.sh" >&2
    exit 1
fi

VERIFICATION_USER="${VERIFICATION_USER:-${SUDO_USER:-$(logname 2>/dev/null || echo root)}}"

echo "=== [1/4] systemd cgroup v2 delegation (Delegate=yes) ==="
# Rootless dockerdがcgroup v2経由でメモリ/CPU/pids制限(既存のtools/benchmark/
# run_benchmark.py._docker_security_args()が渡す--memory/--cpus/--pids-limit)を
# 実際に適用するための前提条件。user@<uid>.serviceにDelegate=yesを与えないと、
# rootless dockerdはこれらの制限を静かに無視する。
mkdir -p /etc/systemd/system/user@.service.d
cat > /etc/systemd/system/user@.service.d/delegate.conf <<'EOF'
[Service]
Delegate=yes
EOF
systemctl daemon-reload
echo "✅ /etc/systemd/system/user@.service.d/delegate.conf を書き込みました。"

echo "=== [2/4] NVIDIA Container Toolkit: rootless dockerd向けフック設定 ==="
if command -v nvidia-ctk >/dev/null 2>&1; then
    # Rootless環境ではdockerdがcgroupデバイス制御を直接操作できないため、
    # no-cgroups=trueが必須(NVIDIA Container Toolkit公式ドキュメントのRootless手順)。
    nvidia-ctk config --set nvidia-container-cli.no-cgroups=true \
        --in-place --config=/etc/nvidia-container-runtime/config.toml
    echo "✅ /etc/nvidia-container-runtime/config.toml に no-cgroups=true を設定しました。"

    # ユーザーごとのrootless dockerdコンテキストへランタイムを登録する。
    VERIFICATION_HOME="$(getent passwd "${VERIFICATION_USER}" | cut -d: -f6)"
    sudo -u "${VERIFICATION_USER}" env HOME="${VERIFICATION_HOME}" \
        nvidia-ctk runtime configure --runtime=docker \
        --config="${VERIFICATION_HOME}/.config/docker/daemon.json"
    echo "✅ ${VERIFICATION_HOME}/.config/docker/daemon.json にnvidiaランタイムを登録しました。"

    sudo -u "${VERIFICATION_USER}" env XDG_RUNTIME_DIR="/run/user/$(id -u "${VERIFICATION_USER}")" \
        systemctl --user restart docker
    echo "✅ rootless dockerdを再起動しました。"
else
    echo "⚠️  nvidia-ctkが見つかりません。NVIDIA Container Toolkitを先にインストールしてください" >&2
    echo "   (https://github.com/NVIDIA/nvidia-container-toolkit)。この手順はスキップします。" >&2
fi

echo "=== [3/4] VRAM直列化用の絶対パス環境変数(.env.verification)の配置 ==="
# tools/config.py:VRAM_LOCK_PATH / nazokake_core.database:NAZOKAKE_DB_PATH と同じ
# 「絶対パス固定」規約をこの検証サーバーでも再現する(run_api.ps1の既存パターンに倣う)。
VERIFICATION_HOME="${VERIFICATION_HOME:-$(getent passwd "${VERIFICATION_USER}" | cut -d: -f6)}"
REPO_DIR="${REPO_DIR:-${VERIFICATION_HOME}/nazokake_apps}"
ENV_TEMPLATE="$(dirname "${BASH_SOURCE[0]}")/.env.verification.template"
ENV_TARGET="${REPO_DIR}/.env"

if [[ -d "${REPO_DIR}" && -f "${ENV_TEMPLATE}" && ! -f "${ENV_TARGET}" ]]; then
    sed "s|__REPO_DIR__|${REPO_DIR}|g" "${ENV_TEMPLATE}" > "${ENV_TARGET}"
    chown "${VERIFICATION_USER}" "${ENV_TARGET}"
    echo "✅ ${ENV_TARGET} を .env.verification.template から生成しました。"
else
    echo "ℹ️  ${REPO_DIR} が未クローン、またはテンプレート不在、または.envが既存のため" \
        "この手順はスキップします(REPO_DIR環境変数で上書き可能)。"
fi

echo "=== [4/4] 軽量ローカルRAG(Experience Replay)知識ベースの事前ビルド ==="
# tools/knowledge_retriever.pyはtools/ai_knowledge_base.jsonの事前ビルドを前提とする。
if [[ -d "${REPO_DIR}" ]]; then
    sudo -u "${VERIFICATION_USER}" bash -lc "cd '${REPO_DIR}' && uv run python tools/compile_knowledge.py" \
        || echo "⚠️  tools/compile_knowledge.py の実行に失敗しました。手動で再実行してください。" >&2
else
    echo "ℹ️  ${REPO_DIR} が未クローンのため、この手順は手動で実行してください:" \
        "cd ${REPO_DIR} && uv run python tools/compile_knowledge.py"
fi

echo ""
echo "🎉 セットアップ完了。検証には以下を実行してください:"
echo "   cd ${REPO_DIR} && uv run python -m pytest tests/verification_env/test_infra_behavior.py -v"

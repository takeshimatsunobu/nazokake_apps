#!/usr/bin/env bash
# infra/scripts/setup_host.sh
# =====================================================
# 物理Linuxノード(Ubuntu LTS)上に、自律コーディングエージェントを安全に隔離する
# Rootless Docker + NVIDIA Container Toolkit基盤をゼロから構築するプロビジョニング
# スクリプト(instructions/002)。ここで構築した基盤の上で、infra/docker-compose.yml
# (instructions/001)のagent-workspace/gen-engine/data-sync-daemonを稼働させる。
#
# 【infra/verification_env/setup_verification_env.shとの役割分担】検証サーバー用の
# 既存スクリプトは「Docker/NVIDIA Container Toolkitが既に導入済み」であることを前提に、
# rootless dockerd向けの追加設定(cgroup delegation, no-cgroups)のみを行う。このスクリプト
# はそれより前段の、「まっさらな物理Ubuntuマシンに、Docker/Rootless Docker/NVIDIA
# Container Toolkit自体をゼロから導入する」工程を担う(instructions/002の要求範囲)。
# 既存のsystemd Delegate=yes設定はここでは再実装しない
# (infra/verification_env/setup_verification_env.shの担当領域を重複させず、実装の
# 二重化によるドリフトを避けるという本リポジトリの既存方針を踏襲する)。このスクリプト
# 適用後、必要であればinfra/verification_env/setup_verification_env.shも重ねて実行する。
#
# 【このセッションでの検証範囲についての正直な注記】この開発機(Windows、物理Linux
# ノード不在)ではこのスクリプトを実行・動的検証していない
# (infra/verification_env/README.mdの「設計・手順書であり~検証していない」と同じ位置づけ)。
# 適用後は必ずinfra/docs/physical_node_setup.mdの検証コマンドで疎通を確認すること。
#
# 使い方(物理Ubuntuマシン上、sudo権限を持つ一般ユーザーとして実行):
#   CONFIRM_WIPE_DOCKER=yes bash infra/scripts/setup_host.sh
# (このスクリプト全体をsudo/rootとして実行しないこと。Rootless Dockerのセットアップ
#  ツール自体がroot実行を拒否するため、スクリプト内部で必要な箇所のみ個別にsudoを
#  要求する設計にしている。)

set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
    echo "🚨 このスクリプトはroot(sudo経由の丸ごと実行)では動作しません。" >&2
    echo "   Rootless Dockerのセットアップは対象の一般ユーザー権限で行う必要があるため、" >&2
    echo "   一般ユーザーとして 'bash infra/scripts/setup_host.sh' を実行してください" >&2
    echo "   (スクリプト内部で必要な箇所のみ個別にsudoを要求します)。" >&2
    exit 1
fi

if ! grep -qi ubuntu /etc/os-release 2>/dev/null; then
    echo "🚨 このスクリプトはUbuntu LTS専用です(/etc/os-releaseにUbuntuの記載がありません)。" >&2
    echo "   誤ったホスト上でDocker関連パッケージの削除が実行されることを防ぐため停止します。" >&2
    exit 1
fi

# [1/5]で既存のDocker環境(コンテナ・イメージ・ボリュームを含む/var/lib/docker)を
# 破壊的に削除するため、誤爆防止の明示的な確認ゲートを設ける。
if [[ "${CONFIRM_WIPE_DOCKER:-}" != "yes" ]]; then
    echo "🚨 このスクリプトは既存のDockerインストール(/var/lib/docker以下のコンテナ・" >&2
    echo "   イメージ・ボリュームを含む)を完全に削除します。実行するには、" >&2
    echo "   CONFIRM_WIPE_DOCKER=yes を明示的に指定してください。" >&2
    echo "   例: CONFIRM_WIPE_DOCKER=yes bash infra/scripts/setup_host.sh" >&2
    exit 1
fi

TARGET_USER="$(id -un)"

echo "=== [1/5] 既存Dockerの完全削除(依存関係の競合排除) ==="
# Rootless Dockerの公式ドキュメントが明示的に要求する前提: rootfulなdockerd・古い
# docker.ioパッケージが残っていると、ソケット・cgroup・iptables設定が競合し、rootless
# dockerdの起動に失敗する。
sudo systemctl disable --now docker.service docker.socket >/dev/null 2>&1 || true
sudo apt-get remove -y \
    docker docker-engine docker.io containerd runc \
    docker-ce docker-ce-cli docker-buildx-plugin docker-compose-plugin \
    >/dev/null 2>&1 || true
sudo rm -rf /var/lib/docker /var/lib/containerd
echo "✅ 既存のrootful Docker関連パッケージ・データディレクトリを削除しました。"

echo "=== [2/5] cgroup v2 (unified hierarchy) の有効化確認 ==="
# Ubuntu 22.04/24.04 LTSはデフォルトでcgroup v2だが、レガシーカーネルパラメータ等で
# cgroup v1固定になっている場合に備え、明示的に検証・修復する。
if [[ "$(stat -fc %T /sys/fs/cgroup 2>/dev/null || true)" == "cgroup2fs" ]]; then
    echo "✅ cgroup v2 (unified hierarchy) は既に有効です。"
else
    echo "⚠️  cgroup v2が無効です。/etc/default/grubにsystemd.unified_cgroup_hierarchy=1を追記します。"
    sudo cp /etc/default/grub "/etc/default/grub.bak.$$"
    if grep -q '^GRUB_CMDLINE_LINUX=' /etc/default/grub; then
        sudo sed -i \
            's/^GRUB_CMDLINE_LINUX="\(.*\)"$/GRUB_CMDLINE_LINUX="\1 systemd.unified_cgroup_hierarchy=1"/' \
            /etc/default/grub
    else
        echo 'GRUB_CMDLINE_LINUX="systemd.unified_cgroup_hierarchy=1"' | sudo tee -a /etc/default/grub >/dev/null
    fi
    sudo update-grub
    echo "🚨 GRUB設定を更新しました(バックアップ: /etc/default/grub.bak.$$)。" >&2
    echo "   この変更を反映するには再起動が必要です。再起動後にこのスクリプトを再実行してください。" >&2
    exit 1
fi

echo "=== [3/5] Rootless Dockerのインストール(公式dockerd-rootless-setuptool.sh) ==="
sudo apt-get update -qq
sudo apt-get install -y -qq uidmap dbus-user-session fuse-overlayfs curl
if ! command -v dockerd-rootless-setuptool.sh >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com/rootless | sh
fi
dockerd-rootless-setuptool.sh install --force
systemctl --user enable --now docker
sudo loginctl enable-linger "${TARGET_USER}"
echo "✅ Rootless Dockerを ${TARGET_USER} のsystemd --userサービスとしてインストール・起動しました。"
echo "   このシェルで直ちに使うには 'export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock' を実行、"
echo "   または再ログインしてください(~/.bashrc にdockerd-rootless-setuptool.shが追記済み)。"

echo "=== [4/5] NVIDIA Container Toolkitのインストール(常に最新版) ==="
# 【CVE-2026-24260についての正直な技術的前提】このスクリプトの根拠元である
# instructions/002が言及する具体的な修正済みバージョン番号を、ここに固定値として
# ハードコードしない(このAIエージェントの知識カットオフ以降に開示されたCVEのため、
# 「このバージョンで対策済み」と断定的に書くことは、未パッチ状態を「対策済み」と
# 誤認させるリスクの方が大きい)。代わりに、NVIDIA公式apt リポジトリから常に最新版を
# インストール/アップグレードすることで、「その時点で入手可能な最新のセキュリティ
# パッチが常に適用される」ことを構造的に保証する。
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
sudo apt-get update -qq
sudo apt-get install -y nvidia-container-toolkit
sudo apt-get install --only-upgrade -y nvidia-container-toolkit
INSTALLED_VERSION="$(dpkg-query -W -f='${Version}' nvidia-container-toolkit 2>/dev/null || echo unknown)"
echo "✅ NVIDIA Container Toolkit ${INSTALLED_VERSION} をインストールしました。"
echo "   CVE-2026-24260に対する対策が本バージョンに含まれているかは、上記バージョン番号を" >&2
echo "   NVIDIA公式のセキュリティ勧告(https://github.com/NVIDIA/nvidia-container-toolkit の" >&2
echo "   Security Advisories)と必ず照合してください。このスクリプトは判定できません。" >&2

echo "=== [5/5] Rootless Docker向けNVIDIA CDI (Container Device Interface) の構成 ==="
# RootlessモードではdockerdがLinuxのデバイスcgroupを直接操作できないため、legacyの
# --gpus指定ではなくCDI経由でGPUデバイスノードを明示的にコンテナへ注入する
# (infra/verification_env/setup_verification_env.shのno-cgroups=true+ランタイムフック
# 方式とは別の、rootless環境でより確実に動作する標準的手法。instructions/002の要求)。
sudo mkdir -p /etc/cdi
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
echo "✅ /etc/cdi/nvidia.yaml を生成しました。"
echo ""
echo "🚨 【既知の不整合・フォローアップ事項】infra/docker-compose.yml (instructions/001) の" >&2
echo "   gen-engineサービスは現在 deploy.resources.reservations.devices (legacy nvidiaランタイム" >&2
echo "   方式)でGPUを指定している。CDI方式に統一する場合は、そちらを" >&2
echo "   '--device nvidia.com/gpu=all' 相当の指定に書き換える追加作業が別途必要(本スクリプトの" >&2
echo "   範囲外、instructions/002は/infra/scripts, /infra/docsの作成のみを指示している)。" >&2

echo ""
echo "🎉 セットアップ完了。検証手順は infra/docs/physical_node_setup.md を参照してください。"

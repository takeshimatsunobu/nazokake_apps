#!/usr/bin/env bash
# infra/verification_env/startup-script.sh
# =========================================
# 検証サーバー(nazokake-l4-vm)のGCEメタデータ(startup-script)として登録される、
# VM起動時にroot権限で自律実行されるブートストラップスクリプト(instructions/214)。
#
# 【背景】instructions/213は「人間の手動SSHによるブートストラップ」を
# deploy_to_vm.ps1内のgcloud compute ssh --command="..."経由の自動化で置き換える
# よう指示したが、これはinstructions/212で撤廃したばかりのAgent/デプロイ
# パイプラインへのSSH特権実行を再導入するものであり、SREアーキテクチャ設計として
# 矛盾していた(却下済み)。
# 本スクリプトはSSH経由のコマンド実行を一切用いず、GCPのVMメタデータ
# (startup-script)という宣言的な起動時フックにブートストラップ処理を委譲する
# ことで、deploy_to_vm.ps1・Agentのいずれにも特権コマンド実行を追加しない。
#
# 【責務】
#   1. デッドマンズスイッチ(TTL自動シャットダウン、instructions/178)の設定(冪等)。
#      tools/deploy/run_ephemeral_pipeline.ps1は、ローカルプロセスのクラッシュ時にも
#      クラウド側単独でVMを停止させるフェイルセーフとして、GCEの`startup-script`
#      メタデータキーへ`shutdown -h +N`を注入する2行の使い捨てスクリプトを毎回
#      上書き登録していた。GCEの`startup-script`は単一キーであり並存(マージ)
#      できないため、本スクリプト(register_startup_script.ps1経由で永続登録)と
#      そのデッドマンズスイッチがどちらも同じキーへ書き込む以上、後から書いた方が
#      他方を消してしまうという構造的な衝突があった(instructions/214実装時に発見)。
#      これを解消するため、シャットダウン予約そのものを「別スクリプトによる上書き」
#      ではなく本スクリプト自身の無条件・最優先ステップとして常時実行する形へ変更
#      した。TTL値(分)だけを別のメタデータ属性(`deadman-switch-minutes`)として
#      分離することで、register_startup_script.ps1 / run_ephemeral_pipeline.ps1の
#      どちらが最後に`startup-script`キーを上書きしても、本スクリプトの内容自体が
#      共有されている限りデッドマンズスイッチが消えることはない。
#      set -eによって後続ステップの失敗でスクリプト全体が中断されても、この
#      安全装置だけは既に設定済みであることを保証するため、必ず最初に実行する。
#   2. Bareリポジトリ(~/nazokake_apps.git)の初期化(冪等)。
#      infra/verification_env/deploy_pull.shはこのBareリポジトリの存在を前提とする
#      (deploy_to_vm.ps1からのgit push --forceの受け先)。
#   3. Firestore監視(instructions/212: deploy_status_sync.py)に必要な
#      firebase-admin等の依存関係解決(冪等)。
#      作業ディレクトリ(~/nazokake_apps)が未クローンの場合はスキップし、次回起動時
#      (deploy_pull.shによる初回クローン後)に収束する(Fail-Open、instructions/212の
#      Firestore記録自体と同じ「観測性の欠落がデプロイの成功を覆い隠さない」方針)。
#
# 【登録方法】tools/deploy/register_startup_script.ps1(一過性・一回限りの手順)を
# 参照。deploy_to_vm.ps1(デプロイパイプライン本体)は本スクリプトの登録・実行には
# 一切関与しない(責務の分離)。tools/deploy/run_ephemeral_pipeline.ps1も本スクリプト
# を同じ`startup-script`メタデータキーへ登録する(上記1参照)。
#
# 【冪等性】GCEのstartup-scriptメタデータは再起動のたびに毎回実行される。
# 既存の.gitや導入済みパッケージによるエラーを避けるため、全ステップを
# 「既に収束済みなら何もしない」形で実装する。

set -euo pipefail

VERIFICATION_USER="${VERIFICATION_USER:-takes}"
VERIFICATION_HOME="${VERIFICATION_HOME:-$(getent passwd "${VERIFICATION_USER}" | cut -d: -f6)}"
REPO_DIR="${REPO_DIR:-${VERIFICATION_HOME}/nazokake_apps}"
BARE_REPO_DIR="${BARE_REPO_DIR:-${VERIFICATION_HOME}/nazokake_apps.git}"
SHARED_CORE_DIR="${SHARED_CORE_DIR:-${REPO_DIR}/packages/shared_core}"

if [[ "${EUID}" -ne 0 ]]; then
    echo "[startup-script] WARN: root権限外での実行を検出しました。GCEのstartup-script" >&2
    echo "  メタデータ経由ではroot権限で自律実行されるはずです。手動実行する場合は" >&2
    echo "  'sudo bash infra/verification_env/startup-script.sh' を使用してください。" >&2
fi

if [[ -z "${VERIFICATION_HOME}" ]]; then
    echo "[startup-script] FATAL: ユーザー '${VERIFICATION_USER}' のホームディレクトリを解決できませんでした。" >&2
    exit 1
fi

echo "=== [1/3] デッドマンズスイッチ(TTL自動シャットダウン)の設定 ==="
# 【最優先・無条件】以下のBareリポジトリ初期化・依存関係解決がset -euo pipefail
# により途中で失敗しても、この安全装置だけは常に設定済みの状態にするため、他の
# どのステップよりも先に実行する。
DEADMAN_SWITCH_MINUTES_DEFAULT=720
DEADMAN_SWITCH_MINUTES=""
if command -v curl >/dev/null 2>&1; then
    DEADMAN_SWITCH_MINUTES="$(curl -sf -H "Metadata-Flavor: Google" \
        "http://metadata.google.internal/computeMetadata/v1/instance/attributes/deadman-switch-minutes" \
        2>/dev/null || true)"
fi
if ! [[ "${DEADMAN_SWITCH_MINUTES}" =~ ^[0-9]+$ ]]; then
    DEADMAN_SWITCH_MINUTES="${DEADMAN_SWITCH_MINUTES_DEFAULT}"
fi
shutdown -c 2>/dev/null || true
shutdown -h "+${DEADMAN_SWITCH_MINUTES}" \
    || echo "[startup-script] WARN: シャットダウン予約に失敗しました。" >&2
echo "[startup-script] デッドマンズスイッチを設定しました(起動から${DEADMAN_SWITCH_MINUTES}分後に自動シャットダウン)。"

echo "=== [2/3] Bareリポジトリの初期化(冪等) ==="
if [[ -d "${BARE_REPO_DIR}" ]]; then
    echo "[startup-script] Bareリポジトリは既に存在します: ${BARE_REPO_DIR}(スキップ)"
else
    sudo -u "${VERIFICATION_USER}" git init --bare "${BARE_REPO_DIR}"
    echo "[startup-script] Bareリポジトリを初期化しました: ${BARE_REPO_DIR}"
fi

echo "=== [3/3] Firestore監視用の依存関係解決(firebase-admin等、冪等) ==="
if [[ ! -d "${REPO_DIR}/.git" ]]; then
    echo "[startup-script] INFO: ${REPO_DIR} が未クローンのためスキップします。" \
        "deploy_pull.shによる初回クローン後、次回のVM再起動時に収束します。"
elif [[ ! -f "${SHARED_CORE_DIR}/pyproject.toml" ]]; then
    echo "[startup-script] WARN: ${SHARED_CORE_DIR}/pyproject.toml が見つかりません。依存関係解決をスキップします。" >&2
elif ! command -v python3 >/dev/null 2>&1; then
    echo "[startup-script] WARN: python3が見つかりません。依存関係解決をスキップします。" >&2
else
    VENV_DIR="${REPO_DIR}/.venv"
    if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
        sudo -u "${VERIFICATION_USER}" python3 -m venv "${VENV_DIR}"
        echo "[startup-script] 仮想環境を作成しました: ${VENV_DIR}"
    else
        echo "[startup-script] 仮想環境は既に存在します: ${VENV_DIR}(作成をスキップ)"
    fi

    # packages/shared_core/pyproject.toml をSSoTとして依存関係を解決する(firebase-admin
    # のバージョンをこのスクリプト内にハードコードしない)。pip install -eは既に導入済み・
    # 変更なしの場合は事実上no-opであり、何度実行しても安全に収束する。
    sudo -u "${VERIFICATION_USER}" "${VENV_DIR}/bin/pip" install --quiet -e "${SHARED_CORE_DIR}"
    echo "[startup-script] 依存関係解決が完了しました(-e ${SHARED_CORE_DIR})。"
fi

echo "[startup-script] 完了しました。"

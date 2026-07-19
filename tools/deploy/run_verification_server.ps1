<#
.SYNOPSIS
    Nazo-Agent検証サーバー(GCP L4 GPU VM)へのワンタッチ・プロビジョニング/デプロイ
    スクリプト(instructions/164)。

.DESCRIPTION
    以下の手順をすべて自動・直列実行し、手動のインフラ運用(トイル)を排除する:
      1. gcloud compute instances start によるVM起動。
      2. ポート22(SSH)が実際に開通するまでの自動リトライ待機ループ。
      3. git archive によるHEAD時点のソースのZIP化と、gcloud compute scp
         (IAPトンネル経由)によるVMへの転送。
      4. gcloud compute ssh(IAPトンネル経由)でのリモート展開、
         infra/verification_env/setup_verification_env.sh の実行、
         docker compose up -d --build mlops-scheduler によるサイドカー起動。

    【設計上の注記】git archiveはHEAD(直近のコミット)のみをZIP化する(作業ツリーの
    未コミット変更は含まれない)。これは意図的な仕様であり、コミットされていない
    変更を検証サーバーへ持ち込まないための規律である。

    【設計上の注記】data/・run/ディレクトリ(instructions/162)の実データ
    (SQLite DB・VRAMロック)はそもそもgit archiveの対象外(非追跡/.gitignore対象)
    のため、この展開はVM上の既存の永続層・揮発層を一切上書きしない
    (`unzip -o`はアーカイブに含まれるファイルのみを上書きし、それ以外の既存ファイル
    には触れない)。

    【冪等性の証明(instructions/165)】VMが既に起動中、あるいはmlops-scheduler
    コンテナが既に稼働中の状態で誤って再実行しても、エラーでクラッシュしたり
    コンテナを破壊したりせず、安全にあるべき状態へ収束する:
      - Step 1: gcloud compute instances startを無条件に呼ぶのではなく、事前に
        現在のstatusを取得し、既にRUNNINGならスキップする(gcloud自身の冪等性の
        有無を前提にせず、コードで明示的に保証する)。
      - Step 2: SSHが既に開通していれば、リトライループの初回試行で即座に成立し
        ブロックしない。
      - Step 3: git archive/scpは常に冪等(同一パスへの単純な上書き、蓄積無し)。
      - Step 4: リモート側のsetup_verification_env.sh(nvidia-ctk検出時に稼働中の
        rootless dockerdを`systemctl --user restart docker`で再起動する処理を含む)
        は、既に稼働中のコンテナへの実際の影響がrootless Dockerの内部仕様に依存し
        この環境で実機検証できないため、センチナルファイル
        (~/.nazokake_verification_env_provisioned)により初回のみ実行し、以後は
        スキップする(VMのOSレベルプロビジョニングは1度で十分であり、繰り返し
        dockerdを再起動するリスクそのものを構造的に無くす)。一方
        `docker compose up -d --build`はVM状態に関係なく毎回実行する(コードの
        再デプロイ自体は毎回反映させる必要があり、Compose自体は冪等かつ
        Graceful Shutdown対応済み(instructions/161のtools/scheduler_daemon.py)
        のため安全)。

    【自律的リトライ(instructions/166)】GCPのOS Login/IAPの権限プロビジョニングは
    VM起動・SSH開通後も数秒〜数十秒のタイムラグを伴って反映されることがあり、その間の
    `gcloud compute scp`/`gcloud compute ssh`は一時的な認証エラー(Exit Code 1等)で
    失敗しうる。これを「一時的な遅延」と「本当に失敗した」の区別なくフェイルファストで
    人間に手動再実行を求める設計は「ワンタッチ・プロビジョニング」の要件に反するため、
    Step 3(scp)・Step 4(ssh)は`Invoke-GcloudWithRetry`により指数バックオフ付きで
    最大5回まで自動リトライする(1回目失敗時5秒待機、以後倍々に増加)。

    【SSH引数エスケープバグの根本解決】Step 4の複数行リモートスクリプトを
    `--command=$remoteScript`として直接渡す設計は、PowerShell→gcloud CLI→SSH→
    リモートbashの多段エスケープが破綻しExit Code 2でクラッシュする実害があった。
    `--command="bash"`のみを渡し、スクリプト本体は標準入力(パイプ)経由でリモートの
    bashへ流し込む設計へ変更した(引数パーサーを経由しないため構造的に安全)。

.EXAMPLE
    .\tools\deploy\run_verification_server.ps1
    .\tools\deploy\run_verification_server.ps1 -Zone us-east1-b -InstanceName nazokake-l4-vm
#>

[CmdletBinding()]
param(
    [string]$ProjectId = "nazokakeapp-137e5",
    [string]$InstanceName = "nazokake-l4-vm",
    [string]$Zone = "us-east1-b",
    [int]$SshWaitMaxAttempts = 30,
    [int]$SshWaitDelaySeconds = 10,
    [int]$GcloudRetryMaxAttempts = 5,
    [int]$GcloudRetryInitialDelaySeconds = 5
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ArchivePath = Join-Path $ProjectRoot "source.zip"

# 【instructions/166: 自律的リトライ(Exponential Backoff)】GCPのOS Login/IAPの
# 権限プロビジョニングは、VM起動・SSH開通後もタイムラグを伴って反映されることがある。
# この間に発生する一時的な認証エラー(Exit Code 1等)を「本当の失敗」と区別せず即座に
# 異常終了させる設計は、人間へ手動再実行を要求してしまい「ワンタッチ・プロビジョニング」
# の要件に反する。ScriptBlock内の外部コマンド(gcloud)の$LASTEXITCODEを見て、
# 非ゼロなら指数バックオフ(初回$InitialDelaySeconds秒、以後倍々)で最大$MaxAttempts回
# まで自動リトライし、それでも失敗した場合にのみ最終的にエラーとして異常終了する。
function Invoke-GcloudWithRetry {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock,
        [Parameter(Mandatory = $true)][string]$Description,
        [int]$MaxAttempts = $GcloudRetryMaxAttempts,
        [int]$InitialDelaySeconds = $GcloudRetryInitialDelaySeconds
    )

    $delay = $InitialDelaySeconds
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        & $ScriptBlock
        if ($LASTEXITCODE -eq 0) {
            return
        }

        if ($attempt -eq $MaxAttempts) {
            Write-Error ("$Description が $MaxAttempts 回試行しても成功しませんでした" +
                "(最終exit code: $LASTEXITCODE)。OS Login/IAPの権限伝播タイムラグ以外の" +
                "恒久的な問題である可能性があります。")
            exit 1
        }

        Write-Host ("⚠️  $Description が失敗しました(exit code: $LASTEXITCODE, " +
            "試行 $attempt/$MaxAttempts)。GCPの権限プロビジョニングのタイムラグを想定し、" +
            "${delay}秒後に自動リトライします...") -ForegroundColor Yellow
        Start-Sleep -Seconds $delay
        $delay = $delay * 2
    }
}

# --- Step 1: VM起動(冪等) ---------------------------------------------------
# 【冪等性】gcloud compute instances start自身の冪等性(既にRUNNING状態のインスタンス
# に対して呼んだ場合の挙動)を前提にせず、事前にstatusを取得してコード上で明示的に
# 判定する。既にRUNNINGならstart自体を呼ばずスキップする。
Write-Host "🔍 [1/4] VMの現在の状態を確認します: $InstanceName (zone=$Zone) ..." -ForegroundColor Cyan
$currentStatus = (gcloud compute instances describe $InstanceName `
    --project=$ProjectId --zone=$Zone --format="get(status)").Trim()
if ($LASTEXITCODE -ne 0) {
    Write-Error "VMの状態取得に失敗しました($InstanceName, zone=$Zone)。"
    exit 1
}

if ($currentStatus -eq "RUNNING") {
    Write-Host "ℹ️  VMは既にRUNNING状態です。起動処理をスキップします(冪等性)。" -ForegroundColor Yellow
} else {
    Write-Host "🚀 VMを起動します(現在の状態: $currentStatus)..." -ForegroundColor Cyan
    gcloud compute instances start $InstanceName --project=$ProjectId --zone=$Zone
    if ($LASTEXITCODE -ne 0) {
        Write-Error "VMの起動に失敗しました($InstanceName, zone=$Zone)。"
        exit 1
    }
}

# --- Step 2: SSH(ポート22)開通待ち ------------------------------------------
# VM起動直後はOS/sshdの起動完了まで数十秒かかるため、開通を確認してから後続の
# 転送・リモート実行を行う(即座に接続を試みてタイムアウトする事故を防ぐ)。
Write-Host "🔍 [2/4] SSH(ポート22)の開通を待機します..." -ForegroundColor Cyan

$externalIp = (gcloud compute instances describe $InstanceName `
    --project=$ProjectId --zone=$Zone `
    --format="get(networkInterfaces[0].accessConfigs[0].natIP)").Trim()
if ($LASTEXITCODE -ne 0) {
    Write-Error "VMの外部IPアドレスの取得に失敗しました。"
    exit 1
}
if (-not $externalIp) {
    Write-Error ("VM '$InstanceName' に外部IPアドレスが割り当てられていません" +
        "(IAP限定構成等でTest-NetConnectionによる直接到達確認ができない可能性があります)。")
    exit 1
}

$sshReady = $false
for ($attempt = 1; $attempt -le $SshWaitMaxAttempts; $attempt++) {
    Write-Host "    試行 $attempt/$SshWaitMaxAttempts`: ${externalIp}:22 ..."
    $probe = Test-NetConnection -ComputerName $externalIp -Port 22 -WarningAction SilentlyContinue
    if ($probe.TcpTestSucceeded) {
        $sshReady = $true
        break
    }
    Start-Sleep -Seconds $SshWaitDelaySeconds
}

if (-not $sshReady) {
    $totalWaitSec = $SshWaitMaxAttempts * $SshWaitDelaySeconds
    Write-Error "タイムアウト: ${totalWaitSec}秒待機してもポート22が開通しませんでした。"
    exit 1
}
Write-Host "✅ SSHが開通しました。" -ForegroundColor Green

# --- Step 3: ソースのZIP化と転送(IAPトンネル経由) ---------------------------
Write-Host "📦 [3/4] git archiveでHEADをZIP化し、IAPトンネル経由で転送します..." -ForegroundColor Cyan

Push-Location $ProjectRoot
try {
    git archive -o $ArchivePath HEAD
    if ($LASTEXITCODE -ne 0) {
        Write-Error "git archiveによるソースのZIP化に失敗しました。"
        exit 1
    }
} finally {
    Pop-Location
}

# 【instructions/167】Windows環境のgcloud compute scp(内部でpscp.exeを使用)は、
# 宛先パスの`~/`をリモートシェル展開に委ねられず、そのまま解釈しようとしてパス解決
# エラーでクラッシュする(pscp.exe自体はPuTTYのSCP実装であり、bashの`~`展開を行わない)。
# 「宛先ディレクトリを省略してデフォルトのホームディレクトリに依存する」設計はIaCの
# 決定論的原則に反するため、リモートのホームディレクトリを明示的な絶対パスで固定する。
$RemoteSourceZipPath = "/home/takes/source.zip"

Invoke-GcloudWithRetry -Description "gcloud compute scp" -ScriptBlock {
    gcloud compute scp $ArchivePath "${InstanceName}:${RemoteSourceZipPath}" `
        --project=$ProjectId --zone=$Zone --tunnel-through-iap
}

# --- Step 4: リモート展開・セットアップ・サイドカー起動 ------------------------
Write-Host "🛠️  [4/4] リモートでの展開・セットアップ・mlops-scheduler起動を実行します..." -ForegroundColor Cyan

# シングルクォートのhere-string(@'...'@)でPowerShell側の$展開・バックティック展開を
# 一切発生させず、bashスクリプトの`$`をそのままリモートへ渡す(このため、下の
# /home/takes/source.zip は$RemoteSourceZipPathを直接埋め込めず、同じ値をリテラルで
# 手書きしている。変更する場合は上の$RemoteSourceZipPathと必ず一致させること)。
# unzip -o は展開元アーカイブに含まれるファイルのみを上書きするため、data/・run/配下の
# 既存の永続層(SQLite DB)・揮発層(VRAMロック)には一切触れない(instructions/162)。
#
# 【冪等性(instructions/165)】setup_verification_env.sh はnvidia-ctk検出時に
# 既に稼働中のrootless dockerdを`systemctl --user restart docker`で再起動する処理を
# 含む。これが既に稼働中のmlops-schedulerコンテナへ実際に影響するかはrootless Docker
# の内部仕様(containerd-shimアーキテクチャでdockerd再起動をコンテナが生き延びるか)
# に依存し実機検証できないため、センチナルファイルで初回のみ実行し、以後は
# スキップする(2回目以降はこの再起動処理自体が走らないため、検証不能なリスクを
# 構造的に無くす)。一方docker compose up -d --buildはVM状態に関わらず毎回実行する
# (コードの再デプロイは毎回反映させる必要があり、Compose自体は冪等かつ
# instructions/161のGraceful Shutdown対応済みのtools/scheduler_daemon.pyのため安全)。
$remoteScript = @'
set -euo pipefail
if ! command -v unzip >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y unzip
fi
mkdir -p ~/nazokake_apps
unzip -o -q /home/takes/source.zip -d ~/nazokake_apps
cd ~/nazokake_apps

PROVISION_MARKER=~/.nazokake_verification_env_provisioned
if [ ! -f "$PROVISION_MARKER" ]; then
    sudo bash infra/verification_env/setup_verification_env.sh
    touch "$PROVISION_MARKER"
else
    echo "ℹ️  setup_verification_env.sh は既に適用済みのためスキップします(冪等性)。"
fi

docker compose -f infra/verification_env/docker-compose.yml up -d --build mlops-scheduler
'@

# 【SRE差し戻し対応: SSH引数エスケープバグの根本解決】複数行の$remoteScriptを
# そのまま`--command=$remoteScript`へ渡す設計は、PowerShell→gcloud CLIの引数
# パース→SSH→リモートbashという複数層を経由する間にエスケープが破綻し、
# Exit Code 2でクラッシュする実害が確認された。`--command`には単純な固定文字列
# "bash"のみを渡し、複数行スクリプトの本体は標準入力(パイプ)経由でリモートの
# bashへ直接流し込む(`ssh host bash < script.sh`と同じフェイルセーフな構造。
# stdin経由であればPowerShell/gcloud CLI側の引数パーサーを一切経由しないため、
# 複数行・特殊文字によるエスケープ破綻が構造的に発生しない)。
Invoke-GcloudWithRetry -Description "gcloud compute ssh" -ScriptBlock {
    $remoteScript | gcloud compute ssh $InstanceName `
        --project=$ProjectId --zone=$Zone --tunnel-through-iap `
        --command="bash"
}

Write-Host "🎉 ワンタッチ・プロビジョニングが完了しました。" -ForegroundColor Green

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
    [int]$SshWaitDelaySeconds = 10
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ArchivePath = Join-Path $ProjectRoot "source.zip"

# --- Step 1: VM起動 ---------------------------------------------------------
Write-Host "🚀 [1/4] VMを起動します: $InstanceName (zone=$Zone) ..." -ForegroundColor Cyan
gcloud compute instances start $InstanceName --project=$ProjectId --zone=$Zone
if ($LASTEXITCODE -ne 0) {
    Write-Error "VMの起動に失敗しました($InstanceName, zone=$Zone)。"
    exit 1
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

gcloud compute scp $ArchivePath "${InstanceName}:~/source.zip" `
    --project=$ProjectId --zone=$Zone --tunnel-through-iap
if ($LASTEXITCODE -ne 0) {
    Write-Error "gcloud compute scpによる転送に失敗しました。"
    exit 1
}

# --- Step 4: リモート展開・セットアップ・サイドカー起動 ------------------------
Write-Host "🛠️  [4/4] リモートでの展開・セットアップ・mlops-scheduler起動を実行します..." -ForegroundColor Cyan

# シングルクォートのhere-string(@'...'@)でPowerShell側の$展開・バックティック展開を
# 一切発生させず、bashスクリプトの`$`をそのままリモートへ渡す。
# unzip -o は展開元アーカイブに含まれるファイルのみを上書きするため、data/・run/配下の
# 既存の永続層(SQLite DB)・揮発層(VRAMロック)には一切触れない(instructions/162)。
$remoteScript = @'
set -euo pipefail
if ! command -v unzip >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y unzip
fi
mkdir -p ~/nazokake_apps
unzip -o -q ~/source.zip -d ~/nazokake_apps
cd ~/nazokake_apps
sudo bash infra/verification_env/setup_verification_env.sh
docker compose -f infra/verification_env/docker-compose.yml up -d --build mlops-scheduler
'@

gcloud compute ssh $InstanceName `
    --project=$ProjectId --zone=$Zone --tunnel-through-iap `
    --command=$remoteScript
if ($LASTEXITCODE -ne 0) {
    Write-Error "リモートでのセットアップ/コンテナ起動に失敗しました。"
    exit 1
}

Write-Host "🎉 ワンタッチ・プロビジョニングが完了しました。" -ForegroundColor Green

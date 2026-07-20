<#
.SYNOPSIS
    Nazo-Agent検証サーバー(GCP L4 GPU VM)への閉域GitOps(Bareリポジトリ経由のPull型
    デプロイ)キックスクリプト(instructions/187)。tools/deploy/run_verification_server.ps1
    (ZIP圧縮+gcloud compute scp/pscp.exeによる直接ファイル転送)を完全に置き換える。

.DESCRIPTION
    従来方式(instructions/164-167)は、git archiveでHEADをZIP化しgcloud compute scp
    (内部でpscp.exeを使用)でVMへ転送、リモートでunzip -oするだけのClickOps運用だった。
    この方式はVM上の稼働ディレクトリ(~/nazokake_apps)から.git履歴を物理的に喪失させ、
    Nazo-Agentの自律エスカレーション(過去のコミットハッシュとの差分評価・自律ロールバック)
    の前提を構造的に破壊するアンチパターンとしてSRE監査でRejectされた。

    以下の手順に全面刷新する:
      1. gcloud compute instances start によるVM起動(冪等、run_verification_server.ps1
         のStep 1と同一実装)。
      2. ポート22(SSH)開通待ちループ(同Step 2と同一実装)。
      3. VM上にBareリポジトリ(~/nazokake_apps.git)が存在しなければ git init --bare で
         初期化する(冪等)。
      4. ローカル(Windows)からVM上のBareリポジトリへ、固定ブランチ名(既定"deploy")へ
         git push --force する。実際のSSH接続はgcloud_ssh_wrapper.ps1経由でgcloud
         compute ssh(IAPトンネル)へ橋渡しする(GIT_SSH_COMMANDのラップ)。
      5. Push成功後、サーバー上のinfra/verification_env/deploy_pull.shをSSH経由で
         非同期(nohup + disown)にキックする(git fetch/reset --hard→
         setup_verification_env.sh→docker compose up --buildの一連のシーケンスは
         deploy_pull.sh側の責務)。

    【絶対制約】ZIP圧縮(git archive/Compress-Archive)およびpscp.exe等による直接ファイル
    転送ロジックは一切含まない。転送はgitのネイティブなpush/fetchプロトコルのみに依る。

    【既知の限界(instructions/187範囲外)】Step 5はVM側でdeploy_pull.shを非同期に
    キックするのみで、その完了(docker compose up --buildの成否)をこのスクリプト自身は
    待たない。したがって、このプロセスの標準出力をポーリングするダッシュボード
    (apps/evaluator/backend/api/routers/admin.py: deploy.log)には「キックした」旨までしか
    表示されず、VM側の実際のビルド進捗はVM上の~/nazokake_apps_deploy_pull.logにのみ
    記録される。このログをダッシュボードへ中継する仕組みは別チケットの範囲とする。

.EXAMPLE
    .\tools\deploy\deploy_to_vm.ps1
    .\tools\deploy\deploy_to_vm.ps1 -Zone us-east1-b -InstanceName nazokake-l4-vm
#>

[CmdletBinding()]
param(
    [string]$ProjectId = "nazokakeapp-137e5",
    [string]$InstanceName = "nazokake-l4-vm",
    [string]$Zone = "us-east1-b",
    [string]$DeployBranch = "deploy",
    [string]$RemoteUser = "takes",
    [int]$SshWaitMaxAttempts = 30,
    [int]$SshWaitDelaySeconds = 10,
    [int]$GcloudRetryMaxAttempts = 5,
    [int]$GcloudRetryInitialDelaySeconds = 5
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$SshWrapperPath = Join-Path $PSScriptRoot "gcloud_ssh_wrapper.ps1"

# 【instructions/166: 自律的リトライ(Exponential Backoff)】GCPのOS Login/IAPの権限
# プロビジョニングは、VM起動・SSH開通後もタイムラグを伴って反映されることがある。
# run_verification_server.ps1と同一実装(この間の一時的な認証エラーを「本当の失敗」と
# 区別せず即座に異常終了させる設計は「ワンタッチ・プロビジョニング」の要件に反するため)。
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
Write-Host "🔍 [1/5] VMの現在の状態を確認します: $InstanceName (zone=$Zone) ..." -ForegroundColor Cyan
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
Write-Host "🔍 [2/5] SSH(ポート22)の開通を待機します..." -ForegroundColor Cyan

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

# --- Step 3: Bareリポジトリの初期化(冪等) -----------------------------------
Write-Host "🔍 [3/5] VM上のBareリポジトリ(~/nazokake_apps.git)の存在を確認します..." -ForegroundColor Cyan

$bareRepoInitCommand = 'test -d ~/nazokake_apps.git || git init --bare ~/nazokake_apps.git'
Invoke-GcloudWithRetry -Description "Bareリポジトリの初期化確認" -ScriptBlock {
    gcloud compute ssh $InstanceName --project=$ProjectId --zone=$Zone `
        --tunnel-through-iap --command=$bareRepoInitCommand
}

# --- Step 4: BareリポジトリへのGit Push(IAPトンネル経由) ---------------------
Write-Host "📤 [4/5] ブランチ '$DeployBranch' をVM上のBareリポジトリへpushします..." -ForegroundColor Cyan

# 【instructions/187】このVMはIAP完全閉域環境であり素のsshクライアントでは到達できない
# ため、GIT_SSH_COMMANDをgcloud_ssh_wrapper.ps1(gcloud compute ssh --tunnel-through-iap
# への橋渡し)へ差し替える。remote URLに書くホスト名(下記$InstanceName)自体はラッパー内
# では使われない(接続先は-InstanceName/-Zone/-ProjectId引数で固定済み)が、git remote
# 一覧上での可読性のために実際のインスタンス名をそのまま使う。
$env:GIT_SSH_COMMAND = "powershell -NoProfile -ExecutionPolicy Bypass -File " +
    "`"$SshWrapperPath`" -InstanceName $InstanceName -ProjectId $ProjectId -Zone $Zone"

$remoteUrl = "${RemoteUser}@${InstanceName}:~/nazokake_apps.git"

Push-Location $ProjectRoot
try {
    # 【決定論的なリモート名】GitHub等の将来の実ソース管理リモート("origin")との名前
    # 衝突を避けるため、この検証VM専用のリモート名を明示的に分離する。
    $existingRemote = git remote get-url verification-vm 2>$null
    if ($LASTEXITCODE -ne 0) {
        git remote add verification-vm $remoteUrl
    } elseif ($existingRemote -ne $remoteUrl) {
        git remote set-url verification-vm $remoteUrl
    }

    # 【instructions/166を継承】OS Login/IAPの権限プロビジョニングのタイムラグに
    # 起因する一時的な認証エラーを想定し、pushも自動リトライの対象とする。デプロイ専用の
    # 固定ブランチ($DeployBranch)へのforce pushは、開発者間で共有されるブランチではない
    # ため、再実行(冪等な同一コミットの再push)も安全。
    Invoke-GcloudWithRetry -Description "git push (verification-vm)" -ScriptBlock {
        git push --force verification-vm "HEAD:refs/heads/$DeployBranch"
    }
} finally {
    Pop-Location
    Remove-Item Env:\GIT_SSH_COMMAND -ErrorAction SilentlyContinue
}

Write-Host "✅ Pushが完了しました。" -ForegroundColor Green

# --- Step 5: サーバー上のdeploy_pull.shを非同期にキック ------------------------
Write-Host "🚀 [5/5] deploy_pull.sh を非同期でキックします..." -ForegroundColor Cyan

# nohup + disownで、このSSHコマンド自身の終了(=このgcloud compute sshプロセスの終了)
# を待たずにVM側で継続実行させる(「非同期キック」、instructions/187)。deploy_pull.sh
# 自身の標準出力/標準エラー出力は、VM上の~/nazokake_apps_deploy_pull.logへ蓄積される
# (このダッシュボードのdeploy.logへは中継されない、既知の限界は.SYNOPSISに記載)。
$kickCommand = 'nohup bash ~/nazokake_apps/infra/verification_env/deploy_pull.sh ' +
    '> ~/nazokake_apps_deploy_pull.log 2>&1 < /dev/null & disown; ' +
    'echo "🚀 deploy_pull.sh をバックグラウンドでキックしました(PID: $!)"'

Invoke-GcloudWithRetry -Description "deploy_pull.shの非同期キック" -ScriptBlock {
    gcloud compute ssh $InstanceName --project=$ProjectId --zone=$Zone `
        --tunnel-through-iap --command=$kickCommand
}

Write-Host "🎉 GitOpsデプロイのキックが完了しました。VM側の進捗は " -ForegroundColor Green -NoNewline
Write-Host "~/nazokake_apps_deploy_pull.log" -ForegroundColor Green -NoNewline
Write-Host " を参照してください。" -ForegroundColor Green

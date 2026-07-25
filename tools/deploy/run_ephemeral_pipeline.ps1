<#
.SYNOPSIS
    FinOps要件に基づくエフェメラルVM上でのMLOpsパイプライン同期実行スクリプト
    (instructions/177)。

.DESCRIPTION
    tools/deploy/run_verification_server.ps1(VM常時起動+mlops-schedulerサイドカーの
    バックグラウンド常駐化)は、検証サーバーの一括セットアップには適するが、GCP VMを
    無条件に起動しっぱなしにするためクラウド課金リスク・API暴走リスクを恒常的に抱える。
    本スクリプトは「必要な時だけ起動し、パイプライン完了後は必ず自律停止する」
    エフェメラルなライフサイクルへ置き換える:
      1. デッドマンズスイッチ(TTL)のメタデータ注入と、GCP VMの起動(冪等)。
      2. SSH(ポート22)開通待ち。
      3. git archiveによるHEADのZIP化とIAPトンネル経由の転送(既存ロジックを踏襲)。
      4. リモート展開・初回プロビジョニング・mlops-schedulerイメージのビルド
         (冪等、Invoke-GcloudWithRetryで自動リトライ)。
      5. 指定されたMLOpsパイプライン(-PipelineScript)を
         `docker compose run --rm --entrypoint python mlops-scheduler tools/<script>`
         としてフォアグラウンドで同期実行し、完了を待機する(1回のみ、リトライなし。
         下記【設計上の注記】参照)。
      6. try...finallyにより、Step 5が正常終了・異常終了(例外/ネットワーク切断)の
         いずれであっても、直後に必ず gcloud compute instances stop を呼び出し、
         VMを自律停止させる(フェイルセーフ)。

    このスクリプト自身の終了コードは、Step 5のパイプライン自体の終了コードを
    そのまま伝播する(呼び出し元のtools/mlops_trigger.pyが成否を判定するため)。
    VM起動前・SSH開通前・転送失敗等、Step 5に到達できなかった場合は終了コード1を返す。

    【設計上の注記: Step 5はリトライしない】run_verification_server.ps1のStep 3/4
    (VM起動確認・scp・ssh)はInvoke-GcloudWithRetryで自動リトライする。これはOS Login/
    IAPの権限プロビジョニングの一時的なタイムラグ(認証エラー)を想定した対策であり、
    「失敗の意味」が明確(一時的)なため安全にリトライできる。一方Step 5の終了コードは
    学習・評価パイプライン自身の正当な失敗(データ不足・評価ゲート未達等)を含みうる。
    これを一時的な認証エラーと同じ扱いで最大5回まで自動リトライすると、正当に失敗した
    学習を無条件に再実行してしまい、コスト・データ整合性の両面で危険なため、Step 5は
    意図的に単一実行とし、終了コードをそのまま呼び出し元へ伝播させる。

    【設計上の注記: デッドマンズスイッチ(instructions/178)】このスクリプト自身が
    ハードクラッシュ(ローカルPCのスリープ・強制終了・ネットワーク切断等)した場合、
    finallyブロックが一切発火せずgcloud compute instances stopが呼ばれない可能性が
    ある(ローカルプロセスの生死に依存するフェイルセーフは単一障害点=SPOFになり、
    VMが無期限に起動し続けるクラウド破産リスクを排除できない)。これを塞ぐため、
    VM起動の直前に必ずstartup-scriptメタデータへ「起動から-DeadmanSwitchMinutes分後の
    自動シャットダウン」を注入する。GCEのstartup-scriptは起動(create/start)ごとに
    実行されるため、ローカル側の生死に一切依存しないクラウド側単独のフェイルセーフ
    として機能する。既定値(720分=12時間)は、tools/mlops_trigger.pyの
    settings.mlops_trigger_stale_after_hours(既定12.0時間、instructions/177で同じ
    理由により延長済み)と時間軸を揃えており、正常に稼働中の長時間学習を誤って
    強制停止しないようにしている。

    【instructions/214での改修: メタデータキー衝突の解消】以前はこのステップが
    使い捨ての2行スクリプト(`#!/bin/bash\nsudo shutdown -h +N\n`)を`startup-script`
    メタデータへ直接書き込んでいたが、tools/deploy/register_startup_script.ps1
    (instructions/214、GitOpsデプロイ用のBareリポジトリ初期化・依存関係解決を行う
    永続的なブートストラップスクリプト)も同じ`startup-script`キーへ書き込むため、
    どちらが最後に実行したかでもう一方の内容を消してしまう構造的な衝突があった。
    これを解消するため、本ステップはinfra/verification_env/startup-script.sh
    (両スクリプトで共有される、デッドマンズスイッチの再設定を自身の最優先ステップ
    として無条件に含む)を`startup-script`として登録し、TTL値だけを別のメタデータ
    属性(`deadman-switch-minutes`)経由で渡すよう変更した。これにより、どちらの
    スクリプトが最後に書き込んでも、デッドマンズスイッチ・ブートストラップ処理の
    いずれも消えることがない。

.EXAMPLE
    .\tools\deploy\run_ephemeral_pipeline.ps1 -PipelineScript mlops_pipeline_nazo.py
    .\tools\deploy\run_ephemeral_pipeline.ps1 -PipelineScript mlops_pipeline_agent.py -Zone us-east1-b
#>

[CmdletBinding()]
param(
    # 【安全対策】任意の文字列をリモートコマンドへ埋め込むとインジェクションの余地が
    # 生まれるため、既知の2パイプラインのみをValidateSetで許可する(ホワイトリスト)。
    [Parameter(Mandatory = $true)]
    [ValidateSet("mlops_pipeline_nazo.py", "mlops_pipeline_agent.py")]
    [string]$PipelineScript,
    [string]$ProjectId = "nazokakeapp-137e5",
    [string]$InstanceName = "nazokake-l4-vm",
    [string]$Zone = "us-east1-b",
    [int]$SshWaitMaxAttempts = 30,
    [int]$SshWaitDelaySeconds = 10,
    [int]$GcloudRetryMaxAttempts = 5,
    [int]$GcloudRetryInitialDelaySeconds = 5,
    # 【instructions/178】クラウドネイティブなデッドマンズスイッチ(TTL)のタイムアウト
    # (分)。既定の720分(12時間)はtools/config.pyのmlops_trigger_stale_after_hours
    # (既定12.0時間)と意図的に揃えている(短すぎると正常な長時間学習を強制停止し、
    # 長すぎるとクラッシュ時のクラウド放置時間が伸びるため、既存のゾンビ回収基準と
    # 同じ時間軸に統一する)。
    [int]$DeadmanSwitchMinutes = 720
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ArchivePath = Join-Path $ProjectRoot "source.zip"

# Step 5に到達できなかった場合の既定の終了コード(VM起動・転送等の前段で失敗した場合)。
$pipelineExitCode = 1

# 【instructions/166: 自律的リトライ(Exponential Backoff)】run_verification_server.ps1と
# 同一実装。OS Login/IAPの権限プロビジョニングのタイムラグに起因する一時的な認証エラー
# のみを対象とし、最大$MaxAttempts回まで指数バックオフで自動リトライする。
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

# 【FinOpsフェイルセーフ】Step 1(VM起動)以降のすべての工程をtry...finallyで包む。
# どこで失敗しても(例外・exit・ネットワーク切断)、finallyでのVM停止が必ず実行される
# (PowerShellの`exit`はtry内で呼ばれてもfinallyを実行してからプロセスを終了する)。
try {
    # --- Step 1: デッドマンズスイッチ(TTL)のメタデータ注入 + VM起動(冪等) -------
    # 【instructions/178】VMが実際にRUNNINGかどうかに関わらず、次にこのVMが起動する
    # (create/start/reboot)たびにstartup-scriptが実行されるよう、起動確認より前に
    # 必ずメタデータを設定する(既にRUNNING中の場合、このメタデータは次回の起動から
    # 有効になる。クラッシュ後の再起動時にも確実に新しいTTLが適用されるようにする
    # ための予防的な順序である)。
    Write-Host ("🕐 [1/5] デッドマンズスイッチ(起動から${DeadmanSwitchMinutes}分後の" +
        "自動シャットダウン)をメタデータへ設定します...") -ForegroundColor Cyan

    # 【instructions/214】register_startup_script.ps1と同じ共有スクリプトを登録する
    # (使い捨ての2行スクリプトではない)。デッドマンズスイッチの再設定はこの共有
    # スクリプト自身の最優先・無条件ステップとして実装されているため、TTL値のみを
    # 別のメタデータ属性経由で渡す(startup-scriptキー衝突の詳細は上記【設計上の
    # 注記】参照)。
    $SharedStartupScriptPath = Join-Path $ProjectRoot "infra\verification_env\startup-script.sh"
    if (-not (Test-Path $SharedStartupScriptPath)) {
        Write-Error "共有startup-scriptが見つかりません: $SharedStartupScriptPath"
        exit 1
    }

    Invoke-GcloudWithRetry -Description "gcloud compute instances add-metadata (startup-script)" -ScriptBlock {
        gcloud compute instances add-metadata $InstanceName --project=$ProjectId --zone=$Zone `
            --metadata-from-file startup-script=$SharedStartupScriptPath
    }
    Invoke-GcloudWithRetry -Description "gcloud compute instances add-metadata (deadman-switch-minutes)" -ScriptBlock {
        gcloud compute instances add-metadata $InstanceName --project=$ProjectId --zone=$Zone `
            --metadata "deadman-switch-minutes=$DeadmanSwitchMinutes"
    }

    Write-Host "🔍 VMの現在の状態を確認します: $InstanceName (zone=$Zone) ..." -ForegroundColor Cyan
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

    # --- Step 2: SSH(ポート22)開通待ち ---------------------------------------
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

    # --- Step 3: ソースのZIP化と転送(IAPトンネル経由) -------------------------
    Write-Host "📦 [3/5] git archiveでHEADをZIP化し、IAPトンネル経由で転送します..." -ForegroundColor Cyan

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

    # 【instructions/167】gcloud compute scp(Windows/pscp.exe)は宛先の`~/`展開に
    # 対応しないため、リモートのホームディレクトリを絶対パスで明示する。
    $RemoteSourceZipPath = "/home/takes/source.zip"

    Invoke-GcloudWithRetry -Description "gcloud compute scp" -ScriptBlock {
        gcloud compute scp $ArchivePath "${InstanceName}:${RemoteSourceZipPath}" `
            --project=$ProjectId --zone=$Zone --tunnel-through-iap
    }

    # --- Step 4: リモート展開・初回プロビジョニング・イメージビルド(冪等) --------
    Write-Host "🛠️  [4/5] リモートでの展開・プロビジョニング・イメージビルドを実行します..." -ForegroundColor Cyan

    # 【instructions/165と同じ冪等性設計】setup_verification_env.shはセンチナル
    # ファイルにより初回のみ実行する。build自体はVM状態に関わらず毎回実行し、コードの
    # 再デプロイを都度反映させる(旧`up -d`によるサイドカー常駐化はここでは行わない。
    # このスクリプトの責務はStep 5での一度限りの同期実行であり、常駐デーモンを
    # 起動しないことこそがエフェメラル化の核心のため)。
    $remoteScript = @'
set -euo pipefail

# 【instructions/171】非ログイン・非対話シェルは~/.bashrcを読み込まないため、
# rootless Dockerのインストーラが追記するPATH拡張・DOCKER_HOSTを明示的に復元する。
export PATH=$HOME/bin:$PATH
export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock

if ! command -v unzip >/dev/null 2>&1; then
    sudo -n apt-get update -y
    sudo -n apt-get install -y unzip
fi
mkdir -p ~/nazokake_apps
unzip -o -q /home/takes/source.zip -d ~/nazokake_apps
cd ~/nazokake_apps

PROVISION_MARKER=~/.nazokake_verification_env_provisioned
if [ ! -f "$PROVISION_MARKER" ]; then
    sudo -n bash infra/verification_env/setup_verification_env.sh
    touch "$PROVISION_MARKER"
else
    echo "ℹ️  setup_verification_env.sh は既に適用済みのためスキップします(冪等性)。"
fi

docker compose -f infra/verification_env/docker-compose.yml build mlops-scheduler
'@

    $RemoteSetupScriptLocalPath = Join-Path $env:TEMP "nazokake_remote_setup.sh"
    $remoteScriptLf = $remoteScript.Replace("`r`n", "`n").Replace("`r", "`n")
    $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($RemoteSetupScriptLocalPath, $remoteScriptLf, $Utf8NoBom)

    $RemoteSetupScriptRemotePath = "/home/takes/remote_setup.sh"
    Invoke-GcloudWithRetry -Description "gcloud compute scp (remote_setup.sh)" -ScriptBlock {
        gcloud compute scp $RemoteSetupScriptLocalPath "${InstanceName}:${RemoteSetupScriptRemotePath}" `
            --project=$ProjectId --zone=$Zone --tunnel-through-iap
    }

    Invoke-GcloudWithRetry -Description "gcloud compute ssh (remote_setup.sh実行)" -ScriptBlock {
        gcloud compute ssh $InstanceName `
            --project=$ProjectId --zone=$Zone --tunnel-through-iap `
            --command="bash $RemoteSetupScriptRemotePath"
    }

    # --- Step 5: パイプラインの同期実行(単一実行、リトライなし) -----------------
    Write-Host "▶️  [5/5] $PipelineScript をエフェメラルVM上で同期実行します(完了まで待機)..." -ForegroundColor Cyan

    # --no-TTYで擬似端末割り当てを明示的に無効化し、非対話SSH経由の実行結果が
    # ローカル端末のTTY有無に依存しないようにする(決定論性)。
    $pipelineCommand = "cd ~/nazokake_apps && docker compose -f infra/verification_env/docker-compose.yml " +
        "run --rm --no-TTY --entrypoint python mlops-scheduler tools/$PipelineScript"

    # 【上記【設計上の注記】】ここは意図的にInvoke-GcloudWithRetryを使わない。1回のみ
    # 実行し、終了コードをそのままこのスクリプト自身の終了コードとして伝播させる。
    gcloud compute ssh $InstanceName `
        --project=$ProjectId --zone=$Zone --tunnel-through-iap `
        --command="$pipelineCommand"
    $pipelineExitCode = $LASTEXITCODE

    if ($pipelineExitCode -eq 0) {
        Write-Host "✅ $PipelineScript が正常終了しました。" -ForegroundColor Green
    } else {
        Write-Host "🚨 $PipelineScript が異常終了しました(exit=$pipelineExitCode)。" -ForegroundColor Red
    }
} finally {
    # --- Teardown: VMの自律停止(必ず実行) -------------------------------------
    Write-Host "🛑 [Teardown] FinOps要件に基づき、VMを停止します: $InstanceName (zone=$Zone) ..." -ForegroundColor Cyan
    gcloud compute instances stop $InstanceName --project=$ProjectId --zone=$Zone
    if ($LASTEXITCODE -ne 0) {
        # VM停止の失敗自体はパイプラインの成否とは独立した別問題であり、ここでexitすると
        # 元々の$pipelineExitCodeを握り潰してしまうため、警告のみ出して処理は継続する。
        Write-Host "⚠️  VMの停止に失敗しました。課金継続を避けるため手動確認が必要です。" -ForegroundColor Red
    } else {
        Write-Host "✅ VMを停止しました。" -ForegroundColor Green
    }
}

exit $pipelineExitCode

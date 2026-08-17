<#
.SYNOPSIS
    ローカルOllama(既定 http://localhost:11434)をCloudflare Tunnel経由で公開し、
    Cloud Runが直接HTTP POSTできるようにする起動ラッパー(Push型アーキテクチャ、
    2026-08-18)。

.DESCRIPTION
    workers/ondemand_elyza_worker.py(Firestoreジョブキューをポーリングする旧
    Pull型アーキテクチャ)は本移行により不要になった。代わりに、自宅PC上の
    Ollamaをこのスクリプトでインターネットへ公開し、払い出された公開URLを
    Cloud Run側の環境変数 LOCAL_ELYZA_ENDPOINT に設定することで、
    apps/evaluator/backend/services/generation.py::generate_via_elyza_direct()
    が直接POSTできるようになる。

    2つのモードをサポートする:
      1. Quick Tunnel(既定、-TunnelName未指定時): 認証不要でその場で使える
         一時URL(https://xxxx.trycloudflare.com)を毎回新規に払い出す。
         動作確認・一時利用向け。プロセスを再起動するたびにURLが変わるため、
         Cloud Run側のLOCAL_ELYZA_ENDPOINTも都度更新が必要になる。
      2. 名前付きTunnel(-TunnelName指定時): 事前に
         `cloudflared tunnel login` → `cloudflared tunnel create <name>` →
         `cloudflared tunnel route dns <name> <your-domain>` で作成した
         固定ドメインのTunnelを起動する。URLは再起動しても変わらないため、
         本番運用にはこちらを強く推奨する(Cloudflare公式もQuick Tunnelを
         本番用途に使わないよう案内している)。

    1. 【環境ガード】 cloudflaredコマンドの存在を検証し、無ければインストール
       手順を案内して即座に exit 1 する。
    2. 【リアルタイムログ】 cloudflaredの標準出力/標準エラーをそのままコンソールへ
       ストリームしつつ、run/audit_reports/ 配下のログファイルにも追記する。
    3. 【URL自動認識】 Quick Tunnelモードでは、cloudflaredが出力する
       "https://*.trycloudflare.com" 形式のURLを正規表現で検出し、
       Cloud Run側に設定すべき環境変数の値としてコンソールへ明示表示し、
       run/audit_reports/elyza_tunnel_url.txt へも書き出す。
    4. 【クラッシュ耐性】 cloudflaredが異常終了した場合のみ、$RestartDelaySec
       秒待って自動再起動するループを回す(Ctrl+C等のGraceful Shutdownでは
       ループを終了する)。

.EXAMPLE
    .\scripts\start_elyza_tunnel.ps1
        # Quick Tunnelを起動し、払い出されたURLをコンソールへ表示する。

    .\scripts\start_elyza_tunnel.ps1 -TunnelName my-elyza-tunnel
        # 事前に作成済みの名前付きTunnelを起動する(URLは固定)。

    .\scripts\start_elyza_tunnel.ps1 -OllamaPort 11435
        # Ollamaが既定と異なるポートで動いている場合。
#>

[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$TunnelName = "",
    [int]$OllamaPort = 11434,
    [int]$RestartDelaySec = 15,
    [switch]$Force
)

$PSNativeCommandUseErrorActionPreference = $false

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # リダイレクト/パイプ実行時は無視(scripts/start_elyza_worker.ps1と同じ理由)
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "run\audit_reports"
$LogFile = Join-Path $LogDir "start_elyza_tunnel.log"
$UrlFile = Join-Path $LogDir "elyza_tunnel_url.txt"
$PidFile = Join-Path $LogDir "start_elyza_tunnel.pid"
$OllamaUrl = "http://localhost:$OllamaPort"

# --- 【環境ガード】 -------------------------------------------------------
$cloudflaredCmd = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflaredCmd) {
    Write-Error @"
cloudflared が見つかりません。以下のいずれかでインストールしてください:
  winget install --id Cloudflare.cloudflared
  (または https://github.com/cloudflare/cloudflared/releases から実行ファイルを取得し、PATHへ配置)
インストール後、再度このスクリプトを実行してください。
"@
    exit 1
}

try {
    $ollamaCheck = Invoke-WebRequest -Uri $OllamaUrl -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
    Write-Host "✅ Ollama ($OllamaUrl) への疎通を確認しました。"
} catch {
    Write-Warning "⚠️ Ollama ($OllamaUrl) への疎通確認に失敗しました(Ollama未起動の可能性)。Tunnel自体は起動を試みます。"
}

# --- 【多重起動防止ガード】 (scripts/start_elyza_worker.ps1と同じ方式) -----
if (-not $Force) {
    $existingTunnels = @(
        Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'tunnel' }
    )
    if ($existingTunnels.Count -gt 0) {
        Write-Error "cloudflared tunnel が既に起動中のため、多重起動を防止しました。以下のプロセスを確認し、不要であれば停止してから再実行してください(意図的に多重起動する場合は -Force):"
        foreach ($p in $existingTunnels) {
            Write-Error "  PID $($p.ProcessId): $($p.CommandLine)"
        }
        exit 1
    }
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Content -Path $PidFile -Value $PID -NoNewline

if ($TunnelName) {
    $tunnelArgs = @("tunnel", "run", "--url", $OllamaUrl, $TunnelName)
    Write-Host "起動: 名前付きTunnel '$TunnelName' ($OllamaUrl を公開)"
    Write-Host "ℹ️ URLは事前に `cloudflared tunnel route dns` で割り当てたドメイン固定です(再起動しても変わりません)。"
} else {
    $tunnelArgs = @("tunnel", "--url", $OllamaUrl)
    Write-Host "起動: Quick Tunnel ($OllamaUrl を公開、URLは毎回変わります)"
}

# https://xxxx-yyyy-zzzz.trycloudflare.com 形式のURLを検出する正規表現。
$urlPattern = 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com'

try {
    while ($true) {
        $startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content -Path $LogFile -Value "[start_elyza_tunnel] $startedAt 起動します。"

        # cloudflaredの出力(URL通知含む)は標準エラーに出るため2>&1で統合し、
        # Tee-Objectでコンソール+ログファイルへ同時出力しつつ、行ごとにURL検出する。
        & cloudflared @tunnelArgs 2>&1 | ForEach-Object {
            $line = $_.ToString()
            Add-Content -Path $LogFile -Value $line
            Write-Host $line
            if ($line -match $urlPattern) {
                $foundUrl = $Matches[0]
                Set-Content -Path $UrlFile -Value $foundUrl -NoNewline
                Write-Host ""
                Write-Host "================================================================"
                Write-Host "  ✅ Tunnel URL を検出しました: $foundUrl"
                Write-Host "  Cloud Run側に以下の環境変数を設定してください:"
                Write-Host "    LOCAL_ELYZA_ENDPOINT=$foundUrl"
                Write-Host "================================================================"
                Write-Host ""
            }
        }
        $exitCode = $LASTEXITCODE

        if ($exitCode -eq 0) {
            Add-Content -Path $LogFile -Value "[start_elyza_tunnel] 正常終了しました(exit=0)。再起動ループを終了します。"
            break
        }

        $retryAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $message = "[start_elyza_tunnel] $retryAt cloudflaredが異常終了しました(exit=$exitCode)。${RestartDelaySec}秒後に自動再起動します。"
        Add-Content -Path $LogFile -Value $message
        Write-Warning $message
        Start-Sleep -Seconds $RestartDelaySec
    }
} finally {
    Remove-Item -Path $PidFile -ErrorAction SilentlyContinue
}

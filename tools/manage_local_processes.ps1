<#
.SYNOPSIS
    ローカル環境のポート占有ゾンビプロセスを浄化し、ELYZAオンデマンドワーカーを
    バックグラウンドデーモンとして起動する (instructions/261)。

.DESCRIPTION
    1. 【ゾンビ浄化】 -ZombiePorts で指定されたポート(既定: 8095。instructions/260の
       調査でrun_api.ps1(7800)ともCloud Run(8080)とも一致しない、出自不明な
       `uv run uvicorn` の残骸プロセス群と判明したポート)をリッスンしている
       uvicornプロセスを検出し終了する。tools/config.pyのSSoTポート(既定7800)と
       一致するポートは、誤って正規のAPIサーバーを巻き込んで停止させないよう、
       安全のため対象から除外する。
    2. 【デーモン起動】 workers/ondemand_elyza_worker.py --loop を検出・冪等に
       バックグラウンド起動する。既にPIDファイルが生存中の同プロセスを指している
       場合は多重起動を回避する(本スクリプト自体がゾンビ増殖源にならないため)。

.EXAMPLE
    .\tools\manage_local_processes.ps1
    .\tools\manage_local_processes.ps1 -ZombiePorts 8095,9999 -SkipWorkerStart
#>

[CmdletBinding()]
param(
    [int[]]$ZombiePorts = @(8095),
    [switch]$SkipWorkerStart
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$LogDir = Join-Path $ProjectRoot "run\audit_reports"
$PidFile = Join-Path $LogDir "ondemand_elyza_worker.pid"
$WorkerScript = Join-Path $ProjectRoot "workers\ondemand_elyza_worker.py"
$WorkerLog = Join-Path $LogDir "service_ondemand_elyza_worker.log"
$WorkerErrLog = "$WorkerLog.err"

if (-not (Test-Path $VenvPython)) {
    Write-Error "仮想環境のPythonが見つかりません: $VenvPython (.venv が壊れている可能性があります)"
    exit 1
}

if (-not (Test-Path $WorkerScript)) {
    Write-Error "ELYZAワーカーが見つかりません: $WorkerScript"
    exit 1
}

# --- 【ポートSSoT】(run_api.ps1と同じ解決ロジック) --------------------------
$SsotPort = [int](& $VenvPython -c "import sys; sys.path.insert(0, r'$ProjectRoot'); from tools.config import settings; print(settings.api_dev_port)")
if ($LASTEXITCODE -ne 0) {
    Write-Error "tools/config.py からSSoTポートを解決できませんでした。"
    exit 1
}

# --- Step 1: ゾンビ浄化 ------------------------------------------------------
foreach ($port in $ZombiePorts) {
    if ($port -eq $SsotPort) {
        Write-Warning "ポート $port はSSoT正規ポート($SsotPort)と一致するため、安全のためスキップします。"
        continue
    }

    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "ℹ️ ポート $port を占有するプロセスはありません。"
        continue
    }

    $targetPids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $targetPids) {
        try {
            $proc = Get-Process -Id $procId -ErrorAction Stop
        } catch {
            continue
        }

        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
        $cmdLine = if ($cim) { $cim.CommandLine } else { "" }

        if ($cmdLine -notmatch "uvicorn") {
            Write-Warning "PID $procId (ポート $port) は uvicorn ではないため、安全のため終了をスキップします: $cmdLine"
            continue
        }

        Write-Host "🔪 ポート $port の残留プロセスを終了します: PID=$procId ($($proc.ProcessName))"
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
        } catch {
            Write-Warning "PID $procId の終了に失敗しました: $_"
        }
    }
}

if ($SkipWorkerStart) {
    Write-Host "✅ ゾンビ浄化のみ完了しました(-SkipWorkerStart指定)。"
    exit 0
}

# --- Step 2: ELYZAワーカーの冪等なデーモン起動 -------------------------------
$alreadyRunning = $false
if (Test-Path $PidFile) {
    $existingPidRaw = (Get-Content $PidFile -Raw -ErrorAction SilentlyContinue)
    if ($existingPidRaw) {
        $existingPid = $existingPidRaw.Trim()
        $existingProc = Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue
        if ($existingProc) {
            $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$existingPid" -ErrorAction SilentlyContinue
            if ($cim -and $cim.CommandLine -match "ondemand_elyza_worker\.py") {
                $alreadyRunning = $true
                Write-Host "✅ ELYZAワーカーは既に稼働中です (PID=$existingPid)。多重起動を回避します。"
            }
        }
    }
}

if (-not $alreadyRunning) {
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }

    Write-Host "🚀 ELYZAオンデマンドワーカーをデーモンとして起動中..."
    $process = Start-Process -FilePath $VenvPython `
        -ArgumentList @($WorkerScript, "--loop") `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $WorkerLog `
        -RedirectStandardError $WorkerErrLog `
        -PassThru

    Set-Content -Path $PidFile -Value $process.Id -NoNewline
    Write-Host "✅ 起動完了: PID=$($process.Id) (stdout: $WorkerLog / stderr: $WorkerErrLog)"
}

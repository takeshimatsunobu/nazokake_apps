<#
.SYNOPSIS
    workers/ondemand_elyza_worker.py --loop をローカルPC(ワーカーサーバー)上で
    確実かつ安全に起動・常駐させるためのラッパースクリプト(instructions/296)。

.DESCRIPTION
    tools/manage_local_processes.ps1(instructions/261)は本ワーカーの冪等な
    バックグラウンド起動とゾンビポート浄化を担うが、起動後にワーカーが異常終了した
    場合の自動再起動(クラッシュ耐性)は持たない。本スクリプトはその欠落を補う、
    単体でも直接実行できる起動ラッパーである。

    1. 【環境ガード】 run_api.ps1 / tools/manage_local_processes.ps1 と同じ規約で、
       仮想環境(.venv)とワーカー本体の存在を検証し、欠落時は即座に exit 1 する。
    2. 【PYTHONPATH】 プロジェクトルートを PYTHONPATH の先頭に追加する(既存の値が
       あれば維持したまま先頭に足すのみで、他ツールの設定を壊さない)。
       ※ ondemand_elyza_worker.py 自身も起動時に sys.path へ自己解決した絶対パスを
       挿入するため実行上は必須ではないが、他プロセス/子プロセスから同モジュール群を
       import する将来のユースケースに備え、指示された責務として明示的に設定する。
    3. 【ログ出力】 標準出力/標準エラーを run/audit_reports/(instructions/265で
       state配置先として定められた既存の安全なディレクトリ。tools/配下には書かない)
       の専用ログファイルへ追記する。
    4. 【クラッシュ耐性】 ワーカーが異常終了(非0終了)した場合のみ、$RestartDelaySec
       秒待って自動再起動するループを回す。Ctrl+C等によるGraceful Shutdown
       (ondemand_elyza_worker.py側でSIGINT/SIGTERMをハンドルし、正常終了時はexit 0を
       返す)ではループを終了する。
    5. 【多重起動防止ガード】 起動前にOSのプロセス一覧を直接調べ、
       ondemand_elyza_worker.py を実行中の python.exe が既に存在すれば警告して
       exit 1 する(instructions/実機インシデント: ゾンビ化した複数ワーカーが
       同じ.vram.lockファイルを奪い合い、VRAM排他制御のセルフロックアウトと
       誤認される実害が発生した)。$PidFile(このラッパー自身のPID)だけでは
       taskkill /F 等で finally が実行されずに残る「陳腐化したPIDファイル」と
       「本当に別プロセスが生きている」を区別できないため、OSプロセス一覧を
       正とする。意図的に多重起動したい場合のみ -Force で無効化できる。

.EXAMPLE
    .\scripts\start_elyza_worker.ps1
    .\scripts\start_elyza_worker.ps1 -Interval 30 -RestartDelaySec 30
    .\scripts\start_elyza_worker.ps1 -Force   # 多重起動防止ガードを意図的に無視する
#>

[CmdletBinding(PositionalBinding = $false)]
param(
    # 0 は「未指定」を表すセンチネル値。省略時は workers/ondemand_elyza_worker.py
    # 側の DEFAULT_POLL_INTERVAL_SEC をそのまま使わせ、既定値をここへ重複して
    # ハードコードしない(run_api.ps1 の -Port と同じSSoT尊重の考え方)。
    [double]$Interval = 0,
    [int]$RestartDelaySec = 15,
    # 多重起動防止ガードを意図的にバイパスする(通常は使わない)。
    [switch]$Force
)

# native実行ファイルの非0終了やstderr出力を、PowerShell側の$ErrorActionPreference
# 経由でterminating errorに昇格させない(PowerShell 7.3+のPSNativeCommandUseError
# ActionPreference対策)。$LASTEXITCODEによる明示的な分岐のみで再起動可否を判定する。
$PSNativeCommandUseErrorActionPreference = $false

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# Python側(generation.py/ondemand_elyza_worker.py)は既にsys.stdout.reconfigure(encoding=
# "utf-8")でUTF-8バイト列を正しく出力しているが、それを描画する側のコンソール(conhost)の
# アクティブなコードページが依然として既定のANSI(日本語環境ではcp932)のままだと、
# UTF-8バイト列がcp932として誤って解釈され文字化けする(実機で確認: "答 Few-shot..."等)。
# [Console]::OutputEncodingはこのプロセスが書き込む実コンソールの出力コードページ
# (chcp 65001相当)を切り替える。子プロセス(python.exe)もこのコンソールに直接アタッチ
# されて描画されるため、この設定が子プロセスの出力の文字化けにも効く。
# 標準出力がリダイレクト/パイプされている場合(実コンソールハンドルが無い)は
# 「The handle is invalid」例外になるが、その場合はそもそもコンソール描画の文字化け
# 問題自体が起こらないため無視してよい。
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # リダイレクト/パイプ実行時は無視(上記コメント参照)
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$WorkerScript = Join-Path $ProjectRoot "workers\ondemand_elyza_worker.py"
$LogDir = Join-Path $ProjectRoot "run\audit_reports"
$LogFile = Join-Path $LogDir "start_elyza_worker.log"
$PidFile = Join-Path $LogDir "start_elyza_worker.pid"

# --- 【環境ガード】 (run_api.ps1と同じ規約) ---------------------------------
$venvActive = [bool]$env:VIRTUAL_ENV
$venvDirExists = Test-Path $VenvDir

if (-not $venvActive -and -not $venvDirExists) {
    Write-Error "仮想環境がアクティベートされていません。'.venv\Scripts\Activate.ps1' を実行してから再試行してください。"
    exit 1
}

if (-not (Test-Path $VenvPython)) {
    Write-Error "仮想環境のPythonが見つかりません: $VenvPython (.venv が壊れている可能性があります)"
    exit 1
}

if (-not (Test-Path $WorkerScript)) {
    Write-Error "ELYZAワーカーが見つかりません: $WorkerScript"
    exit 1
}

# --- 【多重起動防止ガード】 ---------------------------------------------------
# $PidFile(このラッパー自身のPID記録)には頼らない。taskkill /F 等の強制終了では
# finally { Remove-Item -Path $PidFile } が実行されず、PIDファイルだけが
# 「生きているように見えるが実際は死んでいる」状態で残り得る。逆にstart_dev.ps1
# 経由や手動の直接実行(python workers/ondemand_elyza_worker.py)はそもそも
# このPIDファイルの管理下に無い。そのため、起動方法を問わずOSのプロセス一覧を
# 直接調べる方式にする(実機調査でこのセッション中に使い続けた手法と同じ)。
if (-not $Force) {
    $existingWorkers = @(
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'ondemand_elyza_worker\.py' }
    )
    if ($existingWorkers.Count -gt 0) {
        Write-Error "ELYZAワーカーが既に起動中のため、多重起動を防止しました。以下のプロセスを確認し、不要であれば停止してから再実行してください(意図的に多重起動する場合は -Force を付けてください):"
        foreach ($p in $existingWorkers) {
            Write-Error "  PID $($p.ProcessId) (起動時刻: $($p.CreationDate)): $($p.CommandLine)"
        }
        exit 1
    }
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# --- 【PYTHONPATH】 ----------------------------------------------------------
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$ProjectRoot;$env:PYTHONPATH" } else { $ProjectRoot }

$workerArgs = @("--loop")
if ($Interval -gt 0) {
    $workerArgs += @("--interval", "$Interval")
}

Set-Content -Path $PidFile -Value $PID -NoNewline
Write-Host "起動: ondemand_elyza_worker.py $($workerArgs -join ' ') (PID=$PID, cwd=$ProjectRoot, log=$LogFile)"

try {
    while ($true) {
        $startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content -Path $LogFile -Value "[start_elyza_worker] $startedAt 起動します。"

        Push-Location $ProjectRoot
        try {
            & $VenvPython $WorkerScript @workerArgs 2>&1 | Tee-Object -FilePath $LogFile -Append
            $exitCode = $LASTEXITCODE
        } finally {
            Pop-Location
        }

        if ($exitCode -eq 0) {
            Add-Content -Path $LogFile -Value "[start_elyza_worker] ワーカーが正常終了しました(exit=0)。再起動ループを終了します。"
            break
        }

        $retryAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $message = "[start_elyza_worker] $retryAt ワーカーが異常終了しました(exit=$exitCode)。${RestartDelaySec}秒後に自動再起動します。"
        Add-Content -Path $LogFile -Value $message
        Write-Warning $message
        Start-Sleep -Seconds $RestartDelaySec
    }
} finally {
    Remove-Item -Path $PidFile -ErrorAction SilentlyContinue
}

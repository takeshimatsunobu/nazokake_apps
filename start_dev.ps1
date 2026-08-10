<#
.SYNOPSIS
    なぞかけアプリ 統合開発環境 起動スクリプト。

.DESCRIPTION
    バックエンド(FastAPI/uvicorn)とローカルGPUワーカー(ELYZA)を、それぞれ独立した
    PowerShellウィンドウで起動する。

    このスクリプトはバックエンド/ワーカーの起動処理そのものは再実装しない。
    以下の既存の堅牢な起動ラッパーへ委譲する:
      - run_api.ps1                       : env guard・NAZOKAKE_DB_PATH/VRAM_LOCK_PATH の
                                             固定・Alembicマイグレーション・フロントエンド型同期
      - scripts\start_elyza_worker.ps1    : env guard・クラッシュ時の自動再起動ループ・
                                             run\audit_reports\ へのログ記録
    これらを再実装すると、DBパスやVRAMロックパスの固定値がこのスクリプト側とズレて
    (instructions/261と同種の構成ドリフトを起こして)しまうため、常にこのスクリプト経由で
    起動する。

    【今回の修正点(1): 引用符エスケープの構造的排除】
    旧版は Start-Process の -ArgumentList に手組みのエスケープ付き -Command 文字列を
    渡していたため、引用符のネストが壊れると子プロセスが起動時点でサイレントに落ちたり、
    -NoExit が効かず即座にウィンドウが閉じることがあった。本版は -EncodedCommand
    (Base64/UTF-16LE)で子スクリプトを渡すため、引用符エスケープの問題が構造的に
    発生しない。

    【今回の修正点(2): exitがtry/finallyを迂回する問題への対処】
    子ウィンドウ内で run_api.ps1 / start_elyza_worker.ps1 を "& script.ps1" のように
    同一プロセス内で直接呼び出すと、呼び出し先が exit 1 で終了した瞬間にPowerShell
    プロセス全体が即座に終了し、呼び出し元のtry/catch/finally(Read-Hostでの一時停止を
    含む)ごと巻き込まれて消える(実測で確認: finallyブロックは一切実行されない)。
    本版はターゲットスクリプトを "& pwsh.exe -File script.ps1" として別プロセスへ
    切り出して呼ぶ。これによりターゲット側のexitはそのネストしたプロセスだけを終了させ、
    外側(このtry/finallyを持つプロセス)は影響を受けず、$LASTEXITCODEで結果を受け取った
    上でfinally(Read-Host)まで必ず到達する。

    【今回の修正点(3): 非BOMなUTF-8 .ps1ファイルの文字化けパースエラー対策】
    run_api.ps1 / start_elyza_worker.ps1 はUTF-8(BOM無し)で保存されている。
    レガシーの Windows PowerShell 5.1 (powershell.exe) はBOM無しUTF-8の.ps1ファイルを
    既定のANSIコードページ(日本語環境ではcp932)として誤読し、日本語コメント/文字列
    部分でMissingEndParenthesisInExpression等の不可解なParserErrorを起こして即座に
    落ちる(実機で再現・特定済み)。PowerShell 7+ (pwsh.exe) はBOM無しでも正しく
    UTF-8として読むため、pwsh.exeが利用可能な場合は常にそちらを優先する
    (無ければ powershell.exe へフォールバックするが、その場合は上記の文字化け
    リスクが残る旨を起動時に警告する)。

.EXAMPLE
    .\start_dev.ps1
#>

[CmdletBinding()]
param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
Write-Host "なぞかけディスカバリー 開発環境を起動します..." -ForegroundColor Cyan

$projectRoot = $PSScriptRoot
$backendScript = Join-Path $projectRoot "run_api.ps1"
$workerScript = Join-Path $projectRoot "scripts\start_elyza_worker.ps1"

# 【修正点(3)】pwsh.exe(PowerShell 7+)を優先する。BOM無しUTF-8の.ps1を正しく読める
# ため、run_api.ps1等の日本語コメント/文字列での文字化けParserErrorを避けられる。
if (Get-Command pwsh.exe -ErrorAction SilentlyContinue) {
    $shellExe = "pwsh.exe"
} else {
    $shellExe = "powershell.exe"
    Write-Warning "pwsh.exe (PowerShell 7+) が見つかりません。powershell.exe (Windows PowerShell 5.1) で代用しますが、日本語コメントを含む.ps1ファイルの読み込みで文字化けParserErrorが発生する可能性があります。'winget install Microsoft.PowerShell' 等でPowerShell 7+の導入を推奨します。"
}

# --- 【環境ガード】起動対象のラッパースクリプト自体が無ければ即座にフェイルファストする ---
if (-not (Test-Path $backendScript)) {
    Write-Error "バックエンド起動スクリプトが見つかりません: $backendScript"
    exit 1
}
if (-not (Test-Path $workerScript)) {
    Write-Error "ELYZAワーカー起動スクリプトが見つかりません: $workerScript"
    exit 1
}

# 子ウィンドウへ渡すスクリプト本体を組み立てる共通ヘルパー。
# 【重要】$childBodyTemplate は single-quoted here-string(@'...'@)のためこの親スクリプトの
# 変数展開を一切受けない(リテラルのまま)。$_ / $LASTEXITCODE 等は子プロセス側で評価させたい
# ものであり、親側で誤って先に展開させないための意図的な選択。唯一の動的値(呼び出す
# スクリプトの絶対パスとその引数)だけを、後段の.Replace()でプレースホルダへ差し込む。
function New-EncodedGuardedCommand {
    param(
        [Parameter(Mandatory)] [string]$TargetScriptPath,
        # AllowEmptyString: Mandatoryな[string]パラメータは既定で空文字列を「未指定」として
        # 拒否する(実測: "Cannot bind argument to parameter '...' because it is an empty
        # string." で呼び出し元ごと停止する)。引数無しスクリプト(start_elyza_worker.ps1)
        # 呼び出し時に空文字列を渡す必要があるため明示的に許可する。
        [Parameter(Mandatory)] [AllowEmptyString()] [string]$TargetArgsLiteral,  # 例: "-Port 8000" (無ければ空文字)
        [Parameter(Mandatory)] [string]$Label,
        [Parameter(Mandatory)] [string]$ShellExe
    )

    # 【修正点(2)(3)】ターゲットを "& script.ps1" で同一プロセス内実行せず、
    # "& $ShellExe -File script.ps1" として別プロセスへ切り出す。これにより
    # (a) ターゲット側のexitがこのtry/finallyごとプロセスを道連れにしない、
    # (b) $ShellExe=pwsh.exe を使うことでBOM無しUTF-8ファイルの文字化けを避けられる。
    $childBodyTemplate = @'
try {
    # このウィンドウの実コンソールコードページをUTF-8へ切り替える(chcp 65001相当)。
    # Python側(generation.py等)は既にsys.stdout.reconfigure(encoding="utf-8")でUTF-8バイト
    # 列を出力しているが、コンソール(conhost)のアクティブなコードページが既定のANSI
    # (日本語環境ではcp932)のままだとそれを誤って解釈し文字化けする。ここで切り替えて
    # おけば、この後 & で起動する子プロセス(python.exe)の出力も同じコンソールへ描画
    # されるため正しく表示される。標準出力がリダイレクト/パイプされている場合は例外に
    # なるが、その場合はそもそもコンソール描画の文字化け自体が起きないため無視してよい。
    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
    Write-Host "=== __LABEL__ を起動します (__SCRIPT_PATH__) ===" -ForegroundColor Cyan
    & __SHELL_EXE__ -NoProfile -ExecutionPolicy Bypass -File "__SCRIPT_PATH__" __TARGET_ARGS__
    $exitCode = $LASTEXITCODE
} catch {
    $exitCode = 1
    Write-Host ""
    Write-Host "=== __LABEL__ で例外が発生しました ===" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkRed
} finally {
    Write-Host ""
    if ($exitCode -eq 0) {
        Write-Host "=== __LABEL__ は正常終了しました (exit=$exitCode) ===" -ForegroundColor Green
    } else {
        Write-Host "=== __LABEL__ が終了しました (exit=$exitCode)。上のログ(Tracebackなど)を確認してください ===" -ForegroundColor Red
    }
    Read-Host "このウィンドウを閉じるには Enter キーを押してください"
}
'@

    $body = $childBodyTemplate.
        Replace('__LABEL__', $Label).
        Replace('__SCRIPT_PATH__', $TargetScriptPath).
        Replace('__TARGET_ARGS__', $TargetArgsLiteral).
        Replace('__SHELL_EXE__', $ShellExe)

    return [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($body))
}

# 1. バックエンド (FastAPI) の起動
Write-Host "1. バックエンド (FastAPI, port=$Port) を別ウィンドウで起動しています..." -ForegroundColor Yellow
$backendEncoded = New-EncodedGuardedCommand -TargetScriptPath $backendScript -TargetArgsLiteral "-Port $Port" -Label "バックエンド (FastAPI)" -ShellExe $shellExe
Start-Process $shellExe -ArgumentList @(
    "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $backendEncoded
) -WorkingDirectory $projectRoot -WindowStyle Normal

# 2. ローカルGPUワーカー (ELYZA) の起動
Write-Host "2. ローカルGPUワーカー (ELYZA) を別ウィンドウで起動しています..." -ForegroundColor Yellow
$workerEncoded = New-EncodedGuardedCommand -TargetScriptPath $workerScript -TargetArgsLiteral "" -Label "ローカルGPUワーカー (ELYZA)" -ShellExe $shellExe
Start-Process $shellExe -ArgumentList @(
    "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $workerEncoded
) -WorkingDirectory $projectRoot -WindowStyle Normal

Write-Host "すべてのプロセスを起動しました！" -ForegroundColor Green
Write-Host "ブラウザで http://localhost:$Port にアクセスしてください。" -ForegroundColor White
Write-Host "(いずれかのウィンドウでエラーが出た場合、そのウィンドウは自動で閉じません。Tracebackを読んでからEnterを押してください)" -ForegroundColor DarkGray

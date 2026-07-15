<#
.SYNOPSIS
    apps/evaluator/backend の FastAPI (uvicorn) を安全に起動するラッパースクリプト。

.DESCRIPTION
    以下の2つの物理的な運用規律を強制する:
    1. 【環境ガード】 $env:VIRTUAL_ENV が未設定、かつプロジェクトルートに .venv が
       存在しない場合は、依存パッケージ欠落による起動エラーを未然に防ぐため
       即座に exit 1 でフェイルファストする。
    2. 【VRAM保護】 --workers は常に 1 にハードコードする。uvicornをマルチワーカーで
       起動すると、ローカルLLM(Ollama/ELYZA)呼び出しのVRAM排他制御
       (services.generation._OLLAMA_SEMAPHORE)がワーカープロセスごとに別インスタンス化
       されて無意味になり、複数プロセスが同時にVRAMへ殴りかかってOOMを起こすため、
       ユーザーが --workers を渡そうとした場合もエラーとして拒否する。
    3. 【フロントエンド型同期】 uvicorn起動前に tools/export_openapi.py で openapi.json を
       再ダンプし、npm run generate-types で apps/evaluator/frontend/api.d.ts を再生成する。
       これにより起動するたびにフロントエンドのJSDoc型定義がバックエンドの最新契約と
       同期される(Zombie UI/コントラクト破壊の検知漏れを防ぐ)。

.EXAMPLE
    .\run_api.ps1
    .\run_api.ps1 -Port 8080
#>

[CmdletBinding(PositionalBinding = $false)]
param(
    [int]$Port = 7800,
    [string]$BindHost = "127.0.0.1",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

# Pythonの実行環境がOSのANSIコードページ設定に依存せず常にUTF-8を使うよう強制する
# (Windowsのロケール設定によってサイレントにcp932等へフォールバックする事故を防ぐ)。
$env:PYTHONUTF8 = "1"

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$BackendDir = Join-Path $ProjectRoot "apps\evaluator\backend"
$FrontendDir = Join-Path $ProjectRoot "apps\evaluator\frontend"
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

# --- 【環境ガード】 ---------------------------------------------------------
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

if (-not (Test-Path $BackendDir)) {
    Write-Error "バックエンドディレクトリが見つかりません: $BackendDir"
    exit 1
}

# --- 【VRAM保護】 -----------------------------------------------------------
# --workers はここで常に1に固定する。ユーザーが -ExtraArgs 経由で --workers/-w を
# 渡そうとした場合は、無視して起動を継続させるのではなく明示的にエラーで拒否する。
if ($ExtraArgs -and (($ExtraArgs -join " ") -match "(?i)(--workers|-w\b)")) {
    Write-Error "--workers はVRAM保護のため 1 に固定されています。このラッパー経由でのワーカー数指定は許可されていません。"
    exit 1
}

# --- 【フロントエンド型同期】 -------------------------------------------------
$FrontendNodeModules = Join-Path $FrontendDir "node_modules"

if (-not (Test-Path $FrontendNodeModules)) {
    Write-Error "フロントエンドの依存パッケージが未インストールです。'$FrontendDir' で 'npm install' を実行してから再試行してください。"
    exit 1
}

Write-Host "🔄 OpenAPIスキーマをダンプ中..."
& $VenvPython (Join-Path $ProjectRoot "tools\export_openapi.py")
if ($LASTEXITCODE -ne 0) {
    Write-Error "OpenAPIスキーマのダンプに失敗しました(tools\export_openapi.py が非0で終了)。"
    exit 1
}

Write-Host "🔄 フロントエンドの型定義(api.d.ts)を再生成中..."
npm --prefix $FrontendDir run generate-types
if ($LASTEXITCODE -ne 0) {
    Write-Error "フロントエンドの型定義生成に失敗しました(npm run generate-types が非0で終了)。"
    exit 1
}

$uvicornArgs = @(
    "-m", "uvicorn", "main:app",
    "--host", $BindHost,
    "--port", "$Port",
    "--workers", "1"
)

Write-Host "🚀 起動中: uvicorn main:app --host $BindHost --port $Port --workers 1 (cwd: $BackendDir)"

Push-Location $BackendDir
try {
    # main.py の起動時import(絵文字を含むprint文を含む)がWindowsの既定コンソール
    # コードページ(cp932等)でUnicodeEncodeErrorを起こすのを防ぐため、子プロセスの
    # 標準入出力エンコーディングをUTF-8に固定する。
    $env:PYTHONIOENCODING = "utf-8"
    & $VenvPython @uvicornArgs
} finally {
    Pop-Location
}

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
    4. 【スキーマ同期】 uvicorn起動の直前に packages/shared_core で alembic upgrade head を
       同期的に実行し、物理DBスキーマをORMモデル定義の最新状態へ決定論的に揃える。
       NAZOKAKE_DB_PATH をここで絶対パスに固定することで、alembicの実行時cwd
       (packages/shared_core)とuvicornの実行時cwd(apps/evaluator/backend)が異なっても
       両者が同一のDBファイルを指すことを保証する。

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
$SharedCoreDir = Join-Path $ProjectRoot "packages\shared_core"
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

# nazokake_core.database はこの環境変数(未設定時は相対パス "nazokake_local.db")で
# DBファイルの場所を解決する。alembic(cwd: packages/shared_core)とuvicorn
# (cwd: apps/evaluator/backend)がそれぞれ異なるcwdから起動されても同一のDBファイルへ
# 到達するよう、ここで絶対パスに固定して両者へ伝播させる。
$env:NAZOKAKE_DB_PATH = Join-Path $ProjectRoot "nazokake_local.db"

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

# --- 【スキーマ同期】 ---------------------------------------------------------
Write-Host "🔄 Alembicマイグレーションを適用中 (alembic upgrade head)..."
Push-Location $SharedCoreDir
try {
    & $VenvPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Alembicマイグレーションの適用に失敗しました(alembic upgrade head が非0で終了)。"
        exit 1
    }
} finally {
    Pop-Location
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

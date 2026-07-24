$ErrorActionPreference = "Stop"
$PROJECT_ID = "nazokakeapp-137e5"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "🚀 本番環境($PROJECT_ID)へのフル・デプロイ（同期）を開始します..." -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# --- [0] 前提条件のチェック (Pre-flight checks) ---
if (!(Get-Command "gcloud" -ErrorAction SilentlyContinue)) {
    Write-Host "❌ エラー: gcloud CLI がインストールされていないか、パスが通っていません。" -ForegroundColor Red
    exit 1
}
if (!(Get-Command "firebase" -ErrorAction SilentlyContinue)) {
    Write-Host "❌ エラー: firebase CLI がインストールされていないか、パスが通っていません。" -ForegroundColor Red
    exit 1
}

# --- [1] バックエンドのデプロイ (Cloud Run) ---
Write-Host "`n📦 [1/2] バックエンド (Cloud Run) をデプロイしています..." -ForegroundColor Yellow
Write-Host "※コンテナのビルドが行われるため、数分かかります..." -ForegroundColor DarkGray

gcloud run deploy nazokake-backend --source . --project $PROJECT_ID --region asia-northeast1 --allow-unauthenticated
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Cloud Run のデプロイに失敗しました。ログを確認してください。" -ForegroundColor Red
    exit 1
}

# --- [2] フロントエンドのデプロイ (Firebase Hosting) ---
Write-Host "`n📦 [2/2] フロントエンド (Firebase Hosting) をデプロイしています..." -ForegroundColor Yellow
firebase deploy --only hosting --project $PROJECT_ID
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Firebase Hosting のデプロイに失敗しました。ログを確認してください。" -ForegroundColor Red
    exit 1
}

# --- [3] 完了 ---
Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host "✅ すべてのデプロイが完了しました！" -ForegroundColor Green
Write-Host "👉 本番URL: https://${PROJECT_ID}.web.app/" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
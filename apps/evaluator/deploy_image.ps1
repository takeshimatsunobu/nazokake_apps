$ErrorActionPreference = "Continue"
$PROJECT_ID = "nazokakeapp-137e5"
$IMAGE_URL = "us-central1-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/nazokake-backend:latest"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "🚀 構築済みのコンテナ画像から直接デプロイを開始します..." -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. バックエンドのデプロイ (コンテナ画像から直接)
Write-Host "`n📦 [1/2] バックエンド (Cloud Run) をデプロイしています（数秒〜数十秒で終わります）..." -ForegroundColor Yellow
gcloud run deploy nazokake-backend --image $IMAGE_URL --project $PROJECT_ID --region us-central1 --allow-unauthenticated --timeout=600

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n❌ Cloud Run のデプロイに失敗しました。サーバーの起動時（寝起き）にPythonがクラッシュしている可能性があります。" -ForegroundColor Red
    exit 1
}

# 2. フロントエンドのデプロイ (Firebase Hosting)
Write-Host "`n📦 [2/2] フロントエンド (Firebase Hosting) をデプロイしています..." -ForegroundColor Yellow
firebase deploy --only hosting --project $PROJECT_ID

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host "✅ すべてのデプロイが完了しました！" -ForegroundColor Green
Write-Host "👉 本番URL: https://nazokakeapp-137e5.web.app/" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan

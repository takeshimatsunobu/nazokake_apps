# GCPインスタンス構築スクリプト v6 (タイムアウト対策版)
$PROJECT_ID = gcloud config get-value project
$INSTANCE_NAME = "nazokake-l4-vm"
$ZONE = "us-central1-b"
$IMAGE_FAMILY = "common-cu129-ubuntu-2404-nvidia-580"
$IMAGE_PROJECT = "deeplearning-platform-release"

Write-Host "🚀 タイムアウト設定を延長して構築を開始します..." -ForegroundColor Cyan

# タイムアウトを大幅に延長し、非同期構築を試みます
gcloud compute instances create $INSTANCE_NAME `
    --project=$PROJECT_ID `
    --zone=$ZONE `
    --machine-type=g2-standard-4 `
    --maintenance-policy=TERMINATE `
    --accelerator=type=nvidia-l4,count=1 `
    --image-family=$IMAGE_FAMILY `
    --image-project=$IMAGE_PROJECT `
    --boot-disk-size=150GB `
    --boot-disk-type=pd-balanced `
    --metadata="install-nvidia-driver=True" `
    --scopes=https://www.googleapis.com/auth/cloud-platform `
    --timeout=1200

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ インスタンス構築リクエストが正常に送信されました！" -ForegroundColor Green
} else {
    Write-Host "⚠️ 処理がタイムアウトした可能性がありますが、バックグラウンドで構築が続いているか確認します。" -ForegroundColor Yellow
    gcloud compute instances list --filter="name=$INSTANCE_NAME"
}

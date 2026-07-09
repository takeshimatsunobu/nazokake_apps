$PROJECT_ID = "nazokakeapp-137e5"
$INSTANCE_NAME = "nazokake-l4-vm"

# クォータ上限が1であることを確認済みのリージョン配下の全ゾーン
$zones = @(
    "us-central1-a", "us-central1-b", "us-central1-c", "us-central1-f",
    "us-east4-a", "us-east4-b", "us-east4-c",
    "us-west1-a", "us-west1-b", "us-west1-c",
    "us-west4-a", "us-west4-b", "us-west4-c"
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " 🤖 L4 GPU 自動狩猟（ハンター）プロトコル開始" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "全13ゾーンを巡回し、空きスロットを自動で確保します。`n" -ForegroundColor White

foreach ($zone in $zones) {
    Write-Host "🚀 突撃中: [$zone] ..." -ForegroundColor Cyan
    
    # 同期実行で結果を直接受け取る (エラー出力もキャッチ)
    $result = gcloud compute instances create $INSTANCE_NAME `
        --project=$PROJECT_ID `
        --zone=$zone `
        --machine-type=g2-standard-4 `
        --maintenance-policy=TERMINATE `
        --image-family=common-cu129-ubuntu-2404-nvidia-580 `
        --image-project=deeplearning-platform-release `
        --boot-disk-size=150GB `
        --boot-disk-type=pd-balanced `
        --metadata=install-nvidia-driver=True `
        --scopes=https://www.googleapis.com/auth/cloud-platform 2>&1

    # 結果の判定
    if ($LASTEXITCODE -eq 0) {
        Write-Host "🎉 【大勝利】[$zone] にて L4 GPUの確保に成功しました！！" -ForegroundColor Green
        Write-Host "自動狩猟を終了します。" -ForegroundColor Green
        break
    } else {
        Write-Host "❌ [$zone] 在庫切れ (STOCKOUT) - 次のゾーンへ移動します...`n" -ForegroundColor Gray
    }
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " 🏁 巡回プロセス終了" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

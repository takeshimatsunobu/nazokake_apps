$opId = "operation-1779579944663-65284be7377ff-6ee23c34-761015e6"
Write-Host "🔍 強制終了（STOPPING）の真の理由を抽出します..." -ForegroundColor Cyan

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
gcloud compute operations describe $opId --zone=us-central1-b --format="json(error)"
Write-Host "--------------------------------------------------" -ForegroundColor Cyan

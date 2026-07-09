Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " 📡 全米主要データセンターの L4 GPU クォータ一斉スキャン" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

# L4 GPUが安価に提供されている主要USリージョン
$targetRegions = @("us-central1", "us-east4", "us-west1", "us-west4")

foreach ($region in $targetRegions) {
    Write-Host "🔍 スキャン中: $region ..." -ForegroundColor Gray
    $quotaJson = gcloud compute regions describe $region --format="json" 2>$null | ConvertFrom-Json
    
    if ($null -ne $quotaJson) {
        $l4_quota = $quotaJson.quotas | Where-Object { $_.metric -eq "NVIDIA_L4_GPUS" }
        if ($null -ne $l4_quota) {
            $limit = $l4_quota.limit
            if ($limit -gt 0) {
                Write-Host "  ✅ [$region] 突撃可能！ (上限: $limit)" -ForegroundColor Green
            } else {
                Write-Host "  ❌ [$region] クォータ制限あり (上限: 0)" -ForegroundColor Red
            }
        } else {
            Write-Host "  ⚠️ [$region] L4 GPUの提供なし" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  ⚠️ [$region] 情報取得エラー" -ForegroundColor Yellow
    }
}
Write-Host "--------------------------------------------------" -ForegroundColor Cyan

$opId = "operation-1779589917961-6528710e7ebe1-8424c2d3-352a0a32"
$zone = "us-east4-a"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " 🔍 us-east4-a 構築オペレーションの最終結果を判定します" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

Write-Host "`n[1/2] オペレーションの詳細ステータス:" -ForegroundColor Green
gcloud compute operations describe $opId --zone=$zone --format="json(status,error)"

Write-Host "`n[2/2] インスタンスの現在の物理ステータス:" -ForegroundColor Green
$vmStatus = gcloud compute instances describe nazokake-l4-vm --zone=$zone --format="value(status)" 2>$null

if ([string]::IsNullOrWhiteSpace($vmStatus)) {
    Write-Host "⚠️ インスタンスは見つかりませんでした (作成失敗または消滅)" -ForegroundColor Red
} else {
    Write-Host "✅ インスタンスの状態: $vmStatus" -ForegroundColor Cyan
}

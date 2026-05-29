# GCPインスタンス構築スクリプト (東海岸 us-east4 引っ越し版)
$PROJECT_ID = "nazokakeapp-137e5"
$INSTANCE_NAME = "nazokake-l4-vm"
$ZONE = "us-east4-a"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " 🚀 ターゲット変更: us-east4-a (バージニア州) へ突撃します" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

gcloud compute instances create $INSTANCE_NAME `
    --project=$PROJECT_ID `
    --zone=$ZONE `
    --machine-type=g2-standard-4 `
    --maintenance-policy=TERMINATE `
    --image-family=common-cu129-ubuntu-2404-nvidia-580 `
    --image-project=deeplearning-platform-release `
    --boot-disk-size=150GB `
    --boot-disk-type=pd-balanced `
    --metadata=install-nvidia-driver=True `
    --scopes=https://www.googleapis.com/auth/cloud-platform `
    --async

Write-Host "✅ リクエスト送信完了。起動ステータスを監視します..." -ForegroundColor Green
for ($i=0; $i -lt 15; $i++) {
    $status = gcloud compute instances describe $INSTANCE_NAME --zone=$ZONE --format="value(status)" 2>$null
    
    if ($status -eq "RUNNING") {
        Write-Host "🎉 【大勝利】インスタンスが正常に起動しました (RUNNING)！！" -ForegroundColor Green
        break
    } elseif ($status -eq "TERMINATED" -or $status -eq "STOPPING") {
        Write-Host "🚨 構築が強制停止されました。このゾーンも在庫切れ (STOCKOUT) の可能性が高いです。" -ForegroundColor Red
        break
    } elseif ([string]::IsNullOrWhiteSpace($status)) {
        Write-Host "🕒 リソースを確保中... (API応答待ち)" -ForegroundColor Gray
        Start-Sleep -Seconds 30
    } else {
        Write-Host "🏗️ 構築中... 現在の状態: $status" -ForegroundColor Yellow
        Start-Sleep -Seconds 30
    }
}

# GCP L4要塞 完全自動起動＆連携スクリプト

$ErrorActionPreference = "Stop"

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  🚀 GCP L4要塞 (Gemmaエンジン) 自動起動シーケンス開始" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

$instanceName = "nazokake-l4-vm"
$zone = "us-east1-b"

Write-Host "`n[1/4] 🏗️ 要塞インスタンスを起動しています..." -ForegroundColor Yellow
gcloud compute instances start $instanceName --zone=$zone

Write-Host "`n[2/4] ⏳ ネットワーク確立待機中 (20秒)..." -ForegroundColor Yellow
Start-Sleep -Seconds 20

Write-Host "`n[3/4] 📡 新しいTailscale IPを抽出します..." -ForegroundColor Yellow
$l4_ip = gcloud compute ssh $instanceName --zone=$zone --command="tailscale ip -4"

if (-not $l4_ip) {
    Write-Host "🚨 IPの取得に失敗しました。処理を中断します。" -ForegroundColor Red
    exit 1
}

Write-Host "🎯 取得成功: $l4_ip" -ForegroundColor Green

Write-Host "`n[4/4] 🌐 Cloud Run (バックエンド) へIPを反映し、再デプロイします..." -ForegroundColor Yellow
Set-Location -Path "backend"
gcloud run deploy nazokake-backend --source . --region us-central1 --allow-unauthenticated --cpu-throttling --update-env-vars="GCP_L4_IP=$l4_ip"

Write-Host "`n=======================================================" -ForegroundColor Cyan
Write-Host "  🎉 全シーケンス完了！" -ForegroundColor Green
Write-Host "  要塞のIPは自動的にCloud Runへ反映されました。" -ForegroundColor Green
Write-Host "  👉 次は、要塞内で以下のコマンドを実行してGemmaを起動してください:" -ForegroundColor Yellow
Write-Host "  cd ~/nazokake-evaluator/llama.cpp/build/bin && ./llama-server -m ~/nazokake-evaluator/models/gemma-2-9b-it-Q4_K_M.gguf --port 8080 --host 0.0.0.0 -ngl 99 -c 2048" -ForegroundColor Yellow
Write-Host "=======================================================" -ForegroundColor Cyan

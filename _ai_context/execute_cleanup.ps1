# 自動生成された退避用スクリプト
Write-Host '🧹 ゴミ箱(_archive_scripts)への移動を開始します...' -ForegroundColor Cyan
Move-Item -Path 'seed_rag_database_glucose_v2.py' -Destination '_archive_scripts' -Force -ErrorAction SilentlyContinue
Write-Host '  Moved: seed_rag_database_glucose_v2.py'
Write-Host '✅ 退避完了！' -ForegroundColor Green

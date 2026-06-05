$outDir = "$env:USERPROFILE\Downloads"
Write-Host "プロジェクト構造とコードを $outDir に出力しています..."

# ==========================================
# 追加：0. ファイル構成（一覧）を出力
# ==========================================
Write-Host "0. ファイル構成リストを出力中..."
$structureFile = "$outDir\01_structure.txt"
New-Item -ItemType File -Force -Path $structureFile | Out-Null
Get-ChildItem -Path . -Recurse | Where-Object { 
    $_.FullName -notmatch '\\\.git\\' -and 
    $_.FullName -notmatch '\\\.dart_tool\\' -and 
    $_.FullName -notmatch '\\build\\' -and 
    $_.FullName -notmatch '\\\.venv\\' -and 
    $_.FullName -notmatch '__pycache__' 
} | ForEach-Object {
    # カレントディレクトリのパスを削除して、相対パス（フォルダ/ファイル名）のみにする
    $_.FullName.Replace($PWD.Path + '\', '')
} | Add-Content -Path $structureFile -Encoding UTF8


# ==========================================
# 以下、元のスクリプトと同じ
# ==========================================
Write-Host "1. フロントエンド (Dart) コードを出力中..."
$frontendFile = "$outDir\02_frontend_lib.txt"
New-Item -ItemType File -Force -Path $frontendFile | Out-Null
if (Test-Path .\lib) {
    Get-ChildItem -Path .\lib -Recurse -Filter *.dart | ForEach-Object {
        Add-Content -Path $frontendFile -Value "`n`n==========================================`nFile: $($_.FullName)`n==========================================`n"
        Get-Content $_.FullName -Encoding UTF8 | Add-Content -Path $frontendFile -Encoding UTF8
    }
}

Write-Host "2. バックエンド (Python) コードを出力中..."
$backendFile = "$outDir\03_backend.txt"
New-Item -ItemType File -Force -Path $backendFile | Out-Null
if (Test-Path .\backend) {
    Get-ChildItem -Path .\backend -Recurse -Filter *.py | Where-Object { $_.FullName -notmatch '\\\.venv\\' -and $_.FullName -notmatch '__pycache__' } | ForEach-Object {
        Add-Content -Path $backendFile -Value "`n`n==========================================`nFile: $($_.FullName)`n==========================================`n"
        Get-Content $_.FullName -Encoding UTF8 | Add-Content -Path $backendFile -Encoding UTF8
    }
}

Write-Host "3. 設定ファイルを出力中..."
$configFile = "$outDir\04_config.txt"
New-Item -ItemType File -Force -Path $configFile | Out-Null
Get-ChildItem -Path . -Recurse -Include *.yaml, *.json, *.md, Dockerfile, requirements.txt | Where-Object { $_.FullName -notmatch '\\\.git\\' -and $_.FullName -notmatch '\\\.dart_tool\\' -and $_.FullName -notmatch '\\build\\' -and $_.FullName -notmatch '\\\.venv\\' -and $_.Name -ne 'pubspec.lock' } | ForEach-Object {
    Add-Content -Path $configFile -Value "`n`n==========================================`nFile: $($_.FullName)`n==========================================`n"
    Get-Content $_.FullName -Encoding UTF8 | Add-Content -Path $configFile -Encoding UTF8
}

Write-Host "完了しました。ダウンロードフォルダを確認してください。"
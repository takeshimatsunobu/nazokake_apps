# scripts/start_firestore_emulator.ps1
# ================================================
# Firebase Local Emulator Suite(Firestoreのみ)をリポジトリルートの firebase.json /
# .firebaserc 設定で起動する。本番プロジェクト(nazokakeapp-137e5)には一切接続せず、
# ローカルのみで完結する(--project は .firebaserc の default を使う)。
#
# 使い方:
#   .\scripts\start_firestore_emulator.ps1
#
# 起動後、別ターミナルで環境変数 FIRESTORE_EMULATOR_HOST=localhost:8080 を設定した
# プロセス(pytest 等)からの firestore.client() 呼び出しは、自動的にこのエミュレータへ
# ルーティングされる(Firestoreクライアントライブラリ共通の規約。本番資格情報は不要)。
# pytest経由の場合は tests/conftest.py / apps/evaluator/backend/conftest.py が
# このURLを自動設定するため、本スクリプトを起動しておくだけでよい。
#
# UI: http://localhost:4000 (firebase.json の emulators.ui.port)
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "Firestoreエミュレータを起動します(port 8080, UI: http://localhost:4000)..." -ForegroundColor Cyan
firebase emulators:start --only firestore

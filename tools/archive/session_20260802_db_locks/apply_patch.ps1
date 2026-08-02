$TARGET_FILE = "packages/shared_core/nazokake_core/database.py"
$PATCH_FILE = "tools/sqlite_pragma_tuning.patch"
$BACKUP_FILE = "${TARGET_FILE}.bak"

Write-Host "=== SQLite PRAGMA Tuning Patch Application ===" -ForegroundColor Cyan

# バックアップを作成
Copy-Item -Path $TARGET_FILE -Destination $BACKUP_FILE -Force
Write-Host "バックアップを作成しました: $BACKUP_FILE"

# パッチの適用テスト (Dry Run)
try {
    $check_result = git apply --check $PATCH_FILE 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[SUCCESS] パッチの検証に成功しました。適用を実行します..." -ForegroundColor Green
        
        # 実際の適用
        git apply $PATCH_FILE
        
        Write-Host "適用完了。バックアップをクリーンアップします。"
        Remove-Item -Path $BACKUP_FILE -Force
        
        # RuffによるフォーマットとGitコミット
        uv run ruff check --select I --fix $TARGET_FILE
        uv run ruff format $TARGET_FILE
        git add $TARGET_FILE
        git commit -m "perf(db): tune SQLite PRAGMA for high concurrency (Phase 1.5)"
        Write-Host "Commit successful." -ForegroundColor Green
    } else {
        throw "Dry run failed."
    }
} catch {
    Write-Host "[ERROR] パッチの適用に失敗しました。対象ファイルの構造が変更されている可能性があります。" -ForegroundColor Red
    Write-Host "フォールバック処理を開始します..." -ForegroundColor Yellow
    
    # フォールバック処理: 状態を安全に復元し、エラーとして終了（Fail-fast）
    Move-Item -Path $BACKUP_FILE -Destination $TARGET_FILE -Force
    Write-Host "ファイルを元の状態に復元しました。" -ForegroundColor Yellow
    Write-Host "デプロイを中断します。手動でのコード確認が必要です。" -ForegroundColor Red
    exit 1
}

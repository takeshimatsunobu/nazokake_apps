<#
.SYNOPSIS
    プロジェクト構造整理フェーズ2: 本番に不要なファイル群をarchive/配下へ退避する。

.DESCRIPTION
    【絶対原則】このスクリプトはMove-Itemのみを使用し、Remove-Itemは一切呼ばない。
    全ての移動は「退避」であり「削除」ではない。archive/_trash_candidates/配下の
    最終的な削除判断は、実害が無いことを人間が確認してから別途行う(2段階方式)。

    分類根拠(フェーズ1の調査結果):
      - archive/instructions_history/ : tools/instructions/等。コードベース全体の
        コメントが "instructions/NNN" として無数に参照している意思決定トレイルの
        ため削除厳禁。本番デプロイには不要なので隔離するだけ。
      - archive/_trash_candidates/    : バックアップ連番・一回限りのAI支援パッチ/調査
        スクリプト等。apps/evaluator_backup/は.claudeignore自身が「デッドコード、
        どこからも参照されない」と明記済み。
      - tools/content_pipeline/       : build_research_data.py + 日本語CSV5件。
        当初「不要なゴミ」候補だったが、中身を確認した結果
        apps/evaluator/frontend/public/data/research_data.json(なぞかけ研究所の
        実データ)を生成する現役のコンテンツパイプラインと判明したため、ゴミ箱では
        なくtools/配下の正式な置き場へ移動する。

    意図的に対象外(このスクリプトが触らないもの):
      - run/, data/ : 稼働中プロセスが書き込んでいる可能性のあるライブ状態。
        フェーズ4で.gcloudignoreにより除外する方針とし、物理移動はしない。
      - nazokake.db : apps/tactical_cic/webhook_api.py が参照しており、実際の
        読み書きパスへの影響が未検証のため、リスクゼロを優先して現状維持。
      - .ruff_cache/, .pytest_cache/ : ツール実行のたびに自動再生成されるキャッシュ。
        移動しても次回実行時に同じ場所へ再生成されるため無意味(.gitignore対応を
        別途推奨)。

.EXAMPLE
    .\scripts\phase2_archive_reorg.ps1          # 実際に移動する
    .\scripts\phase2_archive_reorg.ps1 -WhatIf  # 何が移動されるかだけ確認する(何もしない)
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

$movedCount = 0
$skippedCount = 0
$failedCount = 0

# --- 【核となる安全装置】 -----------------------------------------------------
# Move-Itemのみを行うラッパー関数。以下を保証する:
#   1. 移動先の親ディレクトリが無ければ -Force で自動作成する。
#   2. 移動元が存在しない場合は静かにスキップする(前回実行済み・元々無い等でも
#      エラーにしない = 再実行安全 / idempotent)。
#   3. 移動先に同名のファイル/ディレクトリが既に存在する場合は、誤って上書き
#      させず失敗として報告する(-Forceでの強制上書きは行わない)。
#   4. 個々の失敗でスクリプト全体を止めない(try/catchで捕捉し、最後にまとめて報告)。
function Move-ToArchive {
    param(
        [Parameter(Mandatory)] [string]$SourceRelativePath,
        [Parameter(Mandatory)] [string]$DestRelativePath
    )

    $source = Join-Path $ProjectRoot $SourceRelativePath
    $dest = Join-Path $ProjectRoot $DestRelativePath

    if (-not (Test-Path -LiteralPath $source)) {
        Write-Host "  ⏭️  スキップ(移動元が存在しません): $SourceRelativePath" -ForegroundColor DarkGray
        $script:skippedCount++
        return
    }

    if (Test-Path -LiteralPath $dest) {
        Write-Host "  ⚠️  失敗(移動先に既に存在します。手動確認してください): $DestRelativePath" -ForegroundColor Red
        $script:failedCount++
        return
    }

    $destParent = Split-Path -Parent $dest
    try {
        if (-not (Test-Path -LiteralPath $destParent)) {
            New-Item -ItemType Directory -Force -Path $destParent | Out-Null
        }
        if ($PSCmdlet.ShouldProcess($source, "Move-Item to $dest")) {
            Move-Item -LiteralPath $source -Destination $dest
            Write-Host "  ✅ 移動: $SourceRelativePath -> $DestRelativePath" -ForegroundColor Green
            $script:movedCount++
        }
    } catch {
        Write-Host "  ❌ 失敗: $SourceRelativePath ($($_.Exception.Message))" -ForegroundColor Red
        $script:failedCount++
    }
}

Write-Host "=== フェーズ2: archive/ への退避を開始します(ProjectRoot=$ProjectRoot) ===" -ForegroundColor Cyan
Write-Host "(Remove-Itemは一切使用しません。全て復元可能な移動のみです)" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# 1. archive/instructions_history/ : 削除厳禁・SSoTとして保持する履歴/文書
# ============================================================================
Write-Host "--- 1. instructions_history へ退避 ---" -ForegroundColor Yellow

Move-ToArchive "tools\instructions" "archive\instructions_history\tools_instructions"
# tools/instructions/ と同じ命名規則(番号_claude_...)の迷子ファイル。本来の置き場へ。
Move-ToArchive "138_claude_mlops_stateless_trigger.txt" "archive\instructions_history\tools_instructions\138_claude_mlops_stateless_trigger.txt"
Move-ToArchive "189_claude_rca_and_triage_dirty_state.txt" "archive\instructions_history\tools_instructions\189_claude_rca_and_triage_dirty_state.txt"

Move-ToArchive "docs" "archive\instructions_history\docs"

foreach ($f in @(
    "SSoT_architecture.md", "GEMINI.md", "project_structure_map.md",
    "agent_logic_map.md", "app_core_logic_map.md"
)) {
    Move-ToArchive $f "archive\instructions_history\root_docs\$f"
}

# ============================================================================
# 2. tools/content_pipeline/ : 現役のコンテンツ生成パイプライン(ゴミではない)
# ============================================================================
Write-Host ""
Write-Host "--- 2. content_pipeline へ移動(ゴミ箱ではない現役ツール) ---" -ForegroundColor Yellow

Move-ToArchive "build_research_data.py" "tools\content_pipeline\build_research_data.py"
foreach ($csv in @(
    "021 なぞかけの生理学的な研究(JSON).csv",
    "022 なぞかけその他の研究の現状.csv",
    "031 日本の言葉遊び文化（完成）.csv",
    "041世界の言語活動調査.(学術的).csv",
    "042 世界の言語活動調査(実態調査).csv"
)) {
    Move-ToArchive $csv "tools\content_pipeline\research_csv_source\$csv"
}

# ============================================================================
# 3. archive/_trash_candidates/ : 確定ゴミ候補(2段階方式・削除はまだしない)
# ============================================================================
Write-Host ""
Write-Host "--- 3. _trash_candidates へ退避 ---" -ForegroundColor Yellow

Move-ToArchive "apps\evaluator_backup" "archive\_trash_candidates\apps_evaluator_backup"
Move-ToArchive "packages\shared_core\build" "archive\_trash_candidates\packages_shared_core_build"

# なぞかけ研究所パイプラインの一回限りの派生パッチ版(build_research_data.pyに統合済み)。
# 上記2.の現役パイプラインとの関連を追跡できるよう専用サブフォルダに分離する。
foreach ($f in @("audit_csv.py", "check7.py", "patch_physio.py", "patch_world.py")) {
    Move-ToArchive $f "archive\_trash_candidates\research_pipeline_superseded\$f"
}

# nazo_agent.py の手動バックアップ連番
foreach ($f in @(
    "nazo_agent.py.bak3", "nazo_agent.py.bak_v47", "nazo_agent.py.bak_v48",
    "nazo_agent.py.bak_v5", "nazo_agent.py.bak_v51", "nazo_agent.py.bak_v52",
    "nazo_agent.py.bak_v57", "nazo_agent.py.bak_v58", "nazo_agent.py.bak_v60"
)) {
    Move-ToArchive $f "archive\_trash_candidates\nazo_agent_backups\$f"
}

# ルート直下の一回限りスクラッチスクリプト
foreach ($f in @(
    "fix_cards.py", "fix_layout.py", "apply_d1_patch.ps1", "code_scanner.py",
    "mdcol_span_2", "patch5.py を作成"
)) {
    Move-ToArchive $f "archive\_trash_candidates\scratch_scripts\$f"
}

# ルート直下のスクラッチテキスト/一時ファイル
foreach ($f in @(
    "wsod_prompt.txt", "test_benchmark_prompt.txt", "test_orchestration.txt",
    "_ast_mapper_test_result.txt", "dependency_scan.txt", "data_source.txt",
    "backend_deps.txt", "root_deps.txt", "import_data.csv", "import_data.tsv",
    "nazokake_lab"
)) {
    Move-ToArchive $f "archive\_trash_candidates\scratch_text\$f"
}

# tools/ 直下の一回限りAI支援パッチ/調査スクリプト(ワイルドカードではなく実測した
# 確定リストを明示することで、将来tools/に追加される正規スクリプトを誤って
# 巻き込まないようにする)。
$toolsOneOffScripts = @(
    "apply_admin_fix.py", "apply_aiosqlite_timeout.py", "apply_aiosqlite_timeout_v2.py",
    "apply_aiosqlite_timeout_v3.py", "apply_best_of_n_safeguards.py",
    "apply_best_of_n_safeguards_fix.py", "apply_best_of_n_safeguards_v2.py",
    "apply_dotenv_override.py", "apply_fix.py", "apply_otel_metrics_v4.py",
    "apply_patch.py", "apply_retry_decorators.py",
    "investigate_db_deep.py", "investigate_db_locks.py", "investigate_db_timeout.py",
    "investigate_elyza.py", "investigate_elyza_logs.py", "investigate_elyza_logs_v2.py",
    "investigate_elyza_v2.py", "investigate_env_path.py", "investigate_worker_best_of_n.py",
    "verify_env_fix.py", "verify_env_fix_v2.py"
)
foreach ($f in $toolsOneOffScripts) {
    Move-ToArchive "tools\$f" "archive\_trash_candidates\tools_one_off_scripts\$f"
}

# apps/batch_factory/ 直下のツール由来デブリ(aiderのキャッシュ・チャット履歴等)
foreach ($f in @(".aider.chat.history.md", ".aider.conf.yml", ".aider.input.history", ".aider.tags.cache.v4")) {
    Move-ToArchive "apps\batch_factory\$f" "archive\_trash_candidates\batch_factory_debris\$f"
}
Move-ToArchive "apps\batch_factory\batch\schemas.py.random_bak" "archive\_trash_candidates\batch_factory_debris\schemas.py.random_bak"

# ============================================================================
# サマリー
# ============================================================================
Write-Host ""
Write-Host "=== 完了 ===" -ForegroundColor Cyan
Write-Host "移動: $movedCount 件  /  スキップ(元々無い): $skippedCount 件  /  失敗: $failedCount 件" -ForegroundColor White
if ($failedCount -gt 0) {
    Write-Host "⚠️ 失敗が $failedCount 件あります。上のログで '❌ 失敗' を確認し、手動対応してください。" -ForegroundColor Red
}
Write-Host ""
Write-Host "次のステップ:" -ForegroundColor Yellow
Write-Host "  1. git status で変更内容を確認する(git mvを使っていないため、git add -A で" -ForegroundColor White
Write-Host "     ステージすると、内容ベースでgitが自動的にrenameとして検出します)。" -ForegroundColor White
Write-Host "  2. .\start_dev.ps1 等でバックエンド/ワーカーが引き続き正常起動することを確認する" -ForegroundColor White
Write-Host "     (今回移動したパスはいずれもDockerfile COPY対象・実行時import対象では無いため" -ForegroundColor White
Write-Host "     理論上は無影響のはずだが、必ず実機確認すること)。" -ForegroundColor White
Write-Host "  3. archive/_trash_candidates/ の中身に問題が無いことを確認できたら、削除するかは" -ForegroundColor White
Write-Host "     別途判断する(このスクリプトは削除しない)。" -ForegroundColor White

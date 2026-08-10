$ErrorActionPreference = "Stop"
Write-Host ">>> [Task D-1] 評価ゲートのインフラエラー(125)のFail-Closed化パッチを適用します..." -ForegroundColor Cyan

$patchScript = "tools/fix_quality_gate.py"
$targetFile = "tools/nazo_agent.py"

# AST操作用Pythonスクリプトの生成
$pythonCode = @'
import ast
import sys
from pathlib import Path

target_file = Path("tools/nazo_agent.py")
source = target_file.read_text(encoding="utf-8")
lines = source.splitlines()
tree = ast.parse(source)

func_node = None
if_node = None

# 1. ターゲットとなる関数とif文ノードの特定
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "_run_post_commit_quality_gate":
        func_node = node
        for child in ast.walk(node):
            if isinstance(child, ast.If):
                try:
                    # if gate is None: の特定
                    if child.test.left.id == "gate" and child.test.comparators[0].value is None:
                        if_node = child
                        break
                except AttributeError:
                    continue
        break

if not func_node or not if_node:
    print("[Fatal] ターゲットノードが見つかりません。")
    sys.exit(1)

# 2. Docstringの修正定義
doc_node = func_node.body[0]
doc_start = None
doc_end = None
if isinstance(doc_node, ast.Expr) and isinstance(doc_node.value, ast.Constant) and isinstance(doc_node.value.value, str):
    doc_start = doc_node.lineno - 1
    doc_end = getattr(doc_node, "end_lineno", doc_start + 1)
    doc_indent = " " * doc_node.col_offset
    new_docstring = f"""{doc_indent}\"\"\"Nazo-Agentがtarget_dirへ実際にコミット(shadow_mode抑止でない、_commit_or_shadow
{doc_indent}がTrueを返した場合のみ呼ぶこと)した直後、6次元定量評価ゲート
{doc_indent}(tools/benchmark/run_benchmark.py: evaluate_6d_quality_gate)を再実行し、退行
{doc_indent}(Fail)を検知した場合は直前のコミットを_autonomous_rollback()で自律的に取り消す
{doc_indent}(instructions/188)。
{doc_indent}
{doc_indent}【Fail-Closedの徹底】
{doc_indent}ゲートを実際に評価できなかった場合(exit code 125等のインフラエラー・レポート未生成・JSON破損)は、
{doc_indent}「非退行」を確認できない状態であるため、未検証コードの通過を防ぐべく例外(RuntimeError)を
{doc_indent}送出し、処理を安全に停止(Fail-Closed)する。
{doc_indent}
{doc_indent}rollback=False(instructions/245: PRドラフト運用)の場合、退行を検知しても
{doc_indent}git revertは行わない。専用の作業ブランチ上のコミットはまだ共有ブランチへ
{doc_indent}マージされていない使い捨ての下書きであり、そこにrevertコミットを積んでも
{doc_indent}レビュー対象のPRを汚すだけで意味がないため、判定結果のみを呼び出し元
{doc_indent}(_create_and_open_pr)へ返し、PR本文への記載を通じて人間の判断に委ねる。
{doc_indent}
{doc_indent}戻り値: ゲートに合格した場合はTrue(ロールバック不要)。退行を明示的に検知した場合はFalse
{doc_indent}(rollback=Trueの場合はさらに_autonomous_rollback()を実行してから返す)。
{doc_indent}ゲート評価不能時はRuntimeErrorによりフェイルクローズする。
{doc_indent}\"\"\""""

# 3. Ifブロックの修正定義
if_start = if_node.lineno - 1
if_end = getattr(if_node, "end_lineno", if_start + 1)
if_indent = " " * if_node.col_offset

new_if_code = f"""{if_indent}if gate is None:
{if_indent}    raise RuntimeError(
{if_indent}        f"[Fail-Closed] 6次元定量評価ゲートを評価できませんでした(exit code={{result.returncode}})。\\n"
{if_indent}        "インフラエラーによる未検証コードの通過(Fail-Open)を防ぐため、処理を安全に停止します。"
{if_indent}    )"""

# 4. 後ろからSurgicalパッチを適用（行番号のズレを防ぐため If -> Docstring の順で置換）
new_lines = lines[:]
new_lines[if_start:if_end] = new_if_code.splitlines()

if doc_start is not None and doc_end is not None:
    new_lines[doc_start:doc_end] = new_docstring.splitlines()

target_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
print(f"Successfully applied surgical patch to {target_file}")
'@

Set-Content -Path $patchScript -Value $pythonCode -Encoding UTF8

Write-Host ">>> AST駆動Surgicalパッチを実行します..." -ForegroundColor Yellow
& uv run python $patchScript
if ($LASTEXITCODE -ne 0) {
    Write-Host ">>> [Fatal] パッチの適用に失敗しました。終了コード: $LASTEXITCODE" -ForegroundColor Red
    Remove-Item -Path $patchScript -Force
    exit 1
}
Remove-Item -Path $patchScript -Force

Write-Host ">>> Ruff によるローカルスコープ検査を実行します..." -ForegroundColor Cyan
& uv run ruff check --fix $targetFile
if ($LASTEXITCODE -ne 0) {
    Write-Host ">>> [Fatal] Ruff検査でエラーが検出されました。" -ForegroundColor Red
    exit 1
}

& uv run ruff format $targetFile
if ($LASTEXITCODE -ne 0) {
    Write-Host ">>> [Fatal] Ruffフォーマットでエラーが検出されました。" -ForegroundColor Red
    exit 1
}

Write-Host ">>> Pyright による最終型検査（Quality Gate）を実行します..." -ForegroundColor Cyan
& uv run pyright $targetFile
if ($LASTEXITCODE -ne 0) {
    Write-Host ">>> [Fatal] Pyrightの型検査でエラーが検出されました。" -ForegroundColor Red
    exit 1
}

Write-Host ">>> [Task D-1 完了] 評価ゲートのインフラエラーをFail-Closed化しました。変更をステージングします。" -ForegroundColor Green
git add $targetFile
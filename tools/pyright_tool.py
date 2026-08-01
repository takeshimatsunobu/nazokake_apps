"""
tools/pyright_tool.py
=======================
Tool-Augmented Agent 用: Pyrightで対象ファイルを型検査し、診断結果を
簡潔な文字列で返すツール。Claudeが推測で型エラーを「直したつもり」になる
ハルシネーションを防ぎ、正確な型情報(エラー箇所・メッセージ・ルール)に基づいて
判断させるためのファクト取得口。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 前処理(Pre-processing)レイヤー: LLMのハルシネーションを誘発しやすい「些細な型の
# 指摘」を除外し、致命的なエラーのみを残す。stub欠落やUnknown系の型推論ノイズは、
# 実行時の正しさとは無関係な指摘であることが多いため、ここで一律にフィルタリングする。
IGNORED_RULES = {
    "reportMissingModuleSource",
    "reportMissingTypeStubs",
    "reportUnknownVariableType",
    "reportUnknownMemberType",
    "reportUnknownArgumentType",
}


def get_type_info(target_file: str) -> str:
    """target_file をPyrightで型検査し、致命的な診断結果のみを簡潔な文字列で返す。

    `uv run pyright --outputjson <target_file>` を実行し、標準出力のJSONを
    パースする。IGNORED_RULES に該当するruleと、severityが"information"の指摘は
    フィルタリングして除外し、残った致命的なエラーのみを1行ずつの人間可読な形式へ
    変換する。Pyright自体の実行に失敗した場合や出力がJSONとして解釈できない場合は
    Error文字列を返す(呼び出し元のツールループを止めない)。
    """
    try:
        result = subprocess.run(
            ["uv", "run", "pyright", "--outputjson", target_file],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as e:
        return f"Error: pyrightの実行に失敗しました: {e}"

    try:
        data = json.loads(result.stdout)
    except Exception as e:
        return f"Error: pyrightの出力(JSON)をパースできませんでした: {e}\n{result.stderr}"

    diagnostics = data.get("generalDiagnostics", [])
    filtered = [
        diag
        for diag in diagnostics
        if diag.get("rule") not in IGNORED_RULES and diag.get("severity") != "information"
    ]

    if not filtered:
        return "型エラーや構文エラーは検出されませんでした。"

    lines = []
    for diag in filtered:
        start = diag.get("range", {}).get("start", {})
        line_no = start.get("line", 0) + 1  # pyrightは0始まり -> 1始まりへ変換
        severity = diag.get("severity", "info")
        message = diag.get("message", "").split("\n")[0]  # 詳細行は省略し要約のみ
        rule = diag.get("rule", "")
        lines.append(f"Line {line_no}: [{severity}] {message} ({rule})")

    return "\n".join(lines)


def _write_gate_log(log_path: Path | None, target_file: str, outcome: dict) -> None:
    """check_types_for_gate()の判定結果を、指定されたrun/audit_reports/配下の
    パスへJSONとして書き出す(instructions/266、トリアージ用)。log_pathが
    Noneの場合は何もしない(CLI単体実行時等、ログ保存が不要なケース)。
    """
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps({"target_file": target_file, **outcome}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def check_types_for_gate(
    target_file: str,
    *,
    cwd: str | None = None,
    log_path: Path | None = None,
) -> dict:
    """target_file をPyrightで型検査し、severity=="error"の診断のみで合否判定する、
    自己修復ループ/CIゲート専用の構造化版(instructions/266: 型保証境界)。

    get_type_info()との違い:
    (1) 判定基準はerrorのみ(警告はゲートの合否に影響させない。致命的でない
        指摘でコミットを止めてしまうと自己修復ループが空回りするため)。
    (2) 戻り値は{"passed": bool, "errors": list[str], "error_lines": list[int],
        "raw_error": str}の構造化dict(呼び出し元がFail-Closed分岐を書きやすく
        するため)。error_linesはerrorsと同じ順序の生の行番号で、
        check_types_for_gate_ratchet()が既存debtとの行単位フィルタに使う
        (文字列"Line N: ..."を後から正規表現で読み直す必要をなくすため)。
    (3) log_pathを指定すると、判定結果をrun/audit_reports/配下へJSONとして
        保存し、後からトリアージできるようにする。

    Pyright自体の実行に失敗した場合(uv/pyright不在・タイムアウト・出力が
    JSONとして解釈不能)は、安全側に倒してpassed=Falseとする(Fail-Closed。
    「型チェックが実行できなかった」ことを「型チェックに通過した」と誤認させ、
    エラーを見逃したまま処理を先へ進めることを防ぐ)。
    """
    try:
        result = subprocess.run(
            ["uv", "run", "pyright", "--outputjson", target_file],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except Exception as e:
        outcome = {
            "passed": False,
            "errors": [],
            "error_lines": [],
            "raw_error": f"pyrightの実行に失敗しました: {e}",
        }
        _write_gate_log(log_path, target_file, outcome)
        return outcome

    try:
        data = json.loads(result.stdout)
    except Exception as e:
        outcome = {
            "passed": False,
            "errors": [],
            "error_lines": [],
            "raw_error": f"pyrightの出力(JSON)をパースできませんでした: {e}\n{result.stderr}",
        }
        _write_gate_log(log_path, target_file, outcome)
        return outcome

    diagnostics = data.get("generalDiagnostics", [])
    errors = []
    error_lines = []
    for diag in diagnostics:
        if diag.get("severity") != "error" or diag.get("rule") in IGNORED_RULES:
            continue
        start = diag.get("range", {}).get("start", {})
        line_no = start.get("line", 0) + 1  # pyrightは0始まり -> 1始まりへ変換
        message = diag.get("message", "").split("\n")[0]  # 詳細行は省略し要約のみ
        rule = diag.get("rule", "")
        errors.append(f"Line {line_no}: {message} ({rule})" if rule else f"Line {line_no}: {message}")
        error_lines.append(line_no)

    outcome = {"passed": not errors, "errors": errors, "error_lines": error_lines, "raw_error": ""}
    _write_gate_log(log_path, target_file, outcome)
    return outcome


def _get_changed_line_ranges(base_ref: str, file_path: str, cwd: str | None = None) -> set[int]:
    """base_refから現在(HEAD)までのdiffで、file_pathに追加・変更された行番号
    (現在のファイル内での行番号)の集合を返す(instructions/266: 行単位ラチェット)。

    `git diff --unified=0`のハンク見出し(`@@ -a,b +c,d @@`)から、追加側
    (`+c,d`)の範囲のみを抽出する。純粋な削除ハンク(dが0)は対象外とする
    (削除しかしていない行に新しい型エラーが生じることはないため)。
    """
    result = subprocess.run(
        ["git", "diff", "--unified=0", f"{base_ref}...HEAD", "--", file_path],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    changed: set[int] = set()
    for line in result.stdout.splitlines():
        if not line.startswith("@@"):
            continue
        match = re.search(r"\+(\d+)(?:,(\d+))?", line)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        if count == 0:
            continue
        changed.update(range(start, start + count))
    return changed


def check_types_for_gate_ratchet(
    target_file: str,
    base_ref: str,
    *,
    cwd: str | None = None,
    log_path: Path | None = None,
) -> dict:
    """check_types_for_gate()のリポジトリ既存debt対応版(instructions/266)。

    ファイル単位ではなく行単位のラチェット方式: このPRで実際に追加・変更された
    行にかかる型エラーのみを合否判定に含める。ファイルに既存の型エラーが
    残っていても、その行にこのPRが触れていなければブロックしない(逆に、既存の
    行を1文字でも編集すればその行の既存エラーはブロック対象になる)。これにより、
    リポジトリ全体の既存debt(instructions/266導入時点でtools/配下だけで338件)を
    是正しないと一切PRをマージできなくなる事態を避けつつ、新規に導入される
    型エラーは確実にブロックする。

    pyright自体の実行が失敗した場合(raw_errorが非空)は、ラチェット判定を
    行わずそのままFail-Closedで返す(「型チェックできなかった」ことを
    debtでマスクしない)。
    """
    full_result = check_types_for_gate(target_file, cwd=cwd, log_path=log_path)
    if full_result["raw_error"] or not full_result["errors"]:
        return full_result

    changed_lines = _get_changed_line_ranges(base_ref, target_file, cwd=cwd)
    kept_errors = []
    kept_lines = []
    for message, line_no in zip(full_result["errors"], full_result["error_lines"]):
        if line_no in changed_lines:
            kept_errors.append(message)
            kept_lines.append(line_no)

    return {"passed": not kept_errors, "errors": kept_errors, "error_lines": kept_lines, "raw_error": ""}


def _discover_changed_py_files(base_ref: str, cwd: str | None = None) -> list[str]:
    """base_refから現在(HEAD)までのdiffで変更されたPythonファイル一覧を返す
    (削除されたファイルは対象外。存在しないファイルをpyrightへ渡してもエラーに
    しかならないため)。
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=d", f"{base_ref}...HEAD", "--", "*.py"],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _run_gate_cli(base_ref: str) -> int:
    """【instructions/266: CI/CDゲートキーパー】base_refとHEADの間で変更された
    Pythonファイルを自動検出し、行単位ラチェット方式(check_types_for_gate_ratchet)
    で型検査する。CI側とHot Loop側(agent_graph.py)の両方が判定基準の実装を
    このモジュール1箇所だけに依存することで、二重実装によるドリフトを防ぐ。
    """
    target_files = _discover_changed_py_files(base_ref)
    if not target_files:
        print(f"'{base_ref}'から変更されたPythonファイルはありません。ゲートをスキップします。")
        return 0

    print("型検査対象(変更されたPythonファイル):")
    for f in target_files:
        print(f"  {f}")

    overall_passed = True
    for target_file in target_files:
        result = check_types_for_gate_ratchet(target_file, base_ref)
        status = "✅ PASS" if result["passed"] else "❌ FAIL"
        print(f"{status}: {target_file}")
        if not result["passed"]:
            overall_passed = False
            if result["raw_error"]:
                print(f"  {result['raw_error']}")
            for err in result["errors"]:
                print(f"  {err}")

    return 0 if overall_passed else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--gate":
        sys.exit(_run_gate_cli(sys.argv[2]))

    if len(sys.argv) != 2:
        print("Usage: python tools/pyright_tool.py <target_file>")
        print("       python tools/pyright_tool.py --gate <base_ref>")
        sys.exit(1)
    print(get_type_info(sys.argv[1]))

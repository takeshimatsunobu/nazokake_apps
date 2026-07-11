"""
tools/pyright_tool.py
=======================
Tool-Augmented Agent 用: Pyrightで対象ファイルを型検査し、診断結果を
簡潔な文字列で返すツール。Claudeが推測で型エラーを「直したつもり」になる
ハルシネーションを防ぎ、正確な型情報(エラー箇所・メッセージ・ルール)に基づいて
判断させるためのファクト取得口。
"""

import json
import subprocess
import sys

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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python tools/pyright_tool.py <target_file>")
        sys.exit(1)
    print(get_type_info(sys.argv[1]))

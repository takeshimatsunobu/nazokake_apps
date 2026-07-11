"""
tools/file_reader.py
======================
Tool-Augmented Agent 用: ファイルの指定行範囲だけを行番号付きで読み込むツール。
"""
from pathlib import Path


def read_file_section(file_path: Path | str, start_line: int, end_line: int) -> str:
    """file_pathのstart_line〜end_line(1始まり・両端含む)を行番号付きで返す。

    ファイル未存在・範囲外指定に対するフェイルセーフを備える。
    """
    path = Path(file_path)
    if not path.exists():
        return f"Error: ファイル '{file_path}' が見つかりません。"

    lines = path.read_text(encoding="utf-8-sig").splitlines()
    total_lines = len(lines)

    start_line = max(1, start_line)
    end_line = min(end_line, total_lines)

    if start_line > end_line:
        return "Error: 開始行が終了行より後になっています。"

    numbered = [f"{i}: {lines[i - 1]}" for i in range(start_line, end_line + 1)]
    header = f"[ファイル: {file_path}] L{start_line}-L{end_line}"
    return header + "\n" + "\n".join(numbered)

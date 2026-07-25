"""
tools/extract_architecture.py
================================
中高生向けシステム仕様書の前準備として、コードベースの真実(Fact)をPythonの
ast モジュールのみを用いて決定論的に抽出し、docs/architecture_facts.json へ
アトミックにダンプするツール(instructions/215)。

【設計方針: 推論による仕様の捏造を禁止】
本ツールはソースコードの静的構造(ファイルパス・クラス名・関数名・引数シグネチャ・
戻り値の型アノテーション・Docstring)だけをASTから機械的に抜き出す。目的・設計意図・
利用シーンといった「推論」を一切行わない(それらはDocstringに書かれている場合のみ
そのまま転記され、書かれていない場合はnullのまま残る)。

【走査対象ディレクトリ(Step 1の自律調査結果)】
リポジトリルート直下を調査した結果、主要なロジックは apps/(Webアプリ本体・
バッチ処理)・tools/(Nazo-Agent・MLOpsパイプライン・各種スクリプト)・
packages/(共有コアドメイン)・infra/(検証環境・データ同期デーモン)の4ディレクトリに
存在すると判断した。data/・docs/・public/・run/ 配下には.pyファイルが存在せず、
tests/配下はテストコード(アーキテクチャそのものではなく検証コード)であるため、
走査対象から除外する。

【除外ルール】tools/ast_mapper.pyが既に実装している除外ルール(_is_excluded /
EXCLUDE_DIR_NAMES: .git・__pycache__・.mypy_cache・node_modules・
unsloth_compiled_cache・audit_reports・venv系ディレクトリ)を再実装せずそのまま
再利用する(実装の二重化によるドリフトを防ぐ、既存のSSoT方針を継承)。

【クラス/関数の抽出単位】モジュール直下のクラス(トップレベルClassDef)は、その
直下のメソッド(トップレベルFunctionDef/AsyncFunctionDef)を子として持つ階層構造で
抽出する。モジュール直下の関数(クラスに属さないトップレベル関数)は別枠の
"functions"として抽出する。クラス内部やネストした関数内部にさらにネストする
関数(クロージャ等)は対象外とする(アーキテクチャ上の公開面ではなく実装の詳細で
あるため)。

【アトミック書き込み】tools/export_metrics.py._atomic_write_jsonと同じ設計思想
(一時ファイルへ書き込み+os.fsync→os.replaceによる不可分な置き換え)。

使い方:
    python tools/extract_architecture.py
"""

from __future__ import annotations

import ast
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from ast_mapper import EXCLUDE_DIR_NAMES, _is_excluded  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR_NAMES = ["apps", "tools", "packages", "infra"]
TARGET_DIRS = [REPO_ROOT / name for name in TARGET_DIR_NAMES]

OUTPUT_PATH = REPO_ROOT / "docs" / "architecture_facts.json"
TMP_PATH = REPO_ROOT / "docs" / "architecture_facts.tmp.json"


def _display_path(py_file: Path) -> str:
    try:
        return str(py_file.relative_to(REPO_ROOT)).replace(os.sep, "/")
    except ValueError:
        return str(py_file)


def _function_fact(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    return {
        "name": node.name,
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "args": ast.unparse(node.args),
        "returns": ast.unparse(node.returns) if node.returns is not None else None,
        "docstring": ast.get_docstring(node),
    }


def _class_fact(node: ast.ClassDef) -> dict:
    methods = [
        _function_fact(child)
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    return {
        "name": node.name,
        "docstring": ast.get_docstring(node),
        "methods": methods,
    }


def extract_file_facts(py_file: Path) -> dict | None:
    """1ファイルをASTでパースし、クラス/関数のファクトを抽出する。
    パース不能なファイル(SyntaxError等)はNoneを返す(呼び出し元でparse_errorsへ記録)。
    """
    source = py_file.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(py_file))

    classes = [
        _class_fact(node) for node in tree.body if isinstance(node, ast.ClassDef)
    ]
    functions = [
        _function_fact(node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    return {
        "path": _display_path(py_file),
        "classes": classes,
        "functions": functions,
    }


def discover_py_files() -> list[Path]:
    """走査対象ディレクトリ配下の.pyファイルを、除外ルール適用後、決定論的な
    順序(パス文字列の昇順)で返す。
    """
    py_files: list[Path] = []
    for target_dir in TARGET_DIRS:
        if not target_dir.exists():
            continue
        for py_file in target_dir.rglob("*.py"):
            if _is_excluded(py_file):
                continue
            py_files.append(py_file)
    return sorted(py_files, key=lambda p: _display_path(p))


def build_architecture_facts() -> dict:
    py_files = discover_py_files()

    files_facts = []
    parse_errors = []
    for py_file in py_files:
        try:
            fact = extract_file_facts(py_file)
        except (SyntaxError, UnicodeDecodeError, ValueError) as e:
            parse_errors.append({"path": _display_path(py_file), "error": f"{type(e).__name__}: {e}"})
            continue
        files_facts.append(fact)

    total_classes = sum(len(f["classes"]) for f in files_facts)
    total_methods = sum(len(c["methods"]) for f in files_facts for c in f["classes"])
    total_functions = sum(len(f["functions"]) for f in files_facts)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "extraction_method": "python ast module (deterministic static analysis; no inference)",
        "scanned_directories": TARGET_DIR_NAMES,
        "excluded_dir_names": sorted(EXCLUDE_DIR_NAMES),
        "files": files_facts,
        "parse_errors": parse_errors,
        "summary": {
            "total_files_scanned": len(py_files),
            "total_files_parsed": len(files_facts),
            "total_parse_errors": len(parse_errors),
            "total_classes": total_classes,
            "total_methods": total_methods,
            "total_module_level_functions": total_functions,
        },
    }


def _atomic_write_json(payload: str, tmp_path: Path, final_path: Path) -> None:
    """一時ファイルへ書き込み+os.fsyncでディスクへの書き込みを確実にした直後、
    os.replaceで目的のファイルへ不可分にすげ替える(tools/export_metrics.py._atomic_write_json
    と同じ設計思想)。
    """
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, final_path)


def main() -> int:
    facts = build_architecture_facts()
    payload = json.dumps(facts, ensure_ascii=False, indent=2)
    _atomic_write_json(payload, TMP_PATH, OUTPUT_PATH)

    summary = facts["summary"]
    print(f"✅ アーキテクチャファクトを書き出しました: {OUTPUT_PATH}")
    print(
        f"   走査対象: {len(TARGET_DIR_NAMES)}ディレクトリ / "
        f"スキャン{summary['total_files_scanned']}ファイル / "
        f"パース成功{summary['total_files_parsed']}ファイル / "
        f"パース失敗{summary['total_parse_errors']}ファイル"
    )
    print(
        f"   クラス{summary['total_classes']}件 / メソッド{summary['total_methods']}件 / "
        f"モジュール直下関数{summary['total_module_level_functions']}件"
    )
    if facts["parse_errors"]:
        print("⚠️  パースに失敗したファイル:", file=sys.stderr)
        for err in facts["parse_errors"]:
            print(f"   - {err['path']}: {err['error']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

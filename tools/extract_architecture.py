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

【拡張: APIエンドポイント一覧とフロントエンドページ構成の追加抽出】
Gemini APIによるシステム仕様書生成(tools/generate_doc_via_gemini.py)の入力ファクトを
充実させるため、以下2種を同じくASTのみで決定論的に追加抽出する(推論禁止の方針は不変)。
  - api_routes: 走査対象内の全.pyファイルについて、関数定義の
    デコレータが `<何か>.get/post/put/delete/patch/websocket("パス")` の形をしている
    箇所を機械的に検出し、{file, base, method, path, function} として記録する
    (FastAPIのAPIRouter/appという名前を決め打ちせず、属性名のみで判定するため
    実際に使われている変数名(router/app/cic_router等)に依存しない)。
    このデコレータ検出のみ、クラス/関数抽出(tree.bodyのトップレベルのみ)とは異なり
    ast.walk()でツリー全体を走査する。ルーター登録は if TYPE_CHECKING やファクトリ
    関数の内部などトップレベル以外にも現れ得るため、検出漏れを避けることを優先した
    意図的な非対称設計(見落としではない)。
  - router_mounts: `<何か>.include_router(対象, prefix=..., tags=...)` 呼び出しを
    同様にast.walk()で検出し、{file, target, prefix, tags} として記録する
    (prefixの実際の値は文字列リテラルの場合のみ、tagsはリスト/タプルリテラルの
    場合のみ転記し、それ以外(変数参照等で静的に確定できない場合)はnullのまま残す)。
  - frontend_pages: フロントエンドがReact/Next.js等のルーター設定を持たず
    静的HTMLファイル(FastAPIのStaticFilesマウント)で構成されているため、
    apps/配下とリポジトリ直下のpublic/配下の*.htmlファイルパスの列挙をもって
    「ページ構成」のファクトとする。単純なglob列挙のため、Jinjaテンプレートや
    fetchで取り込まれるHTML断片など、厳密には「ページ」ではないファイルも
    区別せず含まれる(「推論による絞り込みをしない」という設計方針を優先)。

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

# frontend_pages専用の走査対象(TARGET_DIRSとは別枠。.pyではなく*.htmlを対象とするため)。
FRONTEND_SCAN_DIR_NAMES = ["apps", "public"]
FRONTEND_SCAN_DIRS = [REPO_ROOT / name for name in FRONTEND_SCAN_DIR_NAMES]

ROUTE_METHODS = {"get", "post", "put", "delete", "patch", "websocket"}

# 【フェーズ2の構造整理で移設】docs/ は本番デプロイに不要な文書としてarchive/
# instructions_history/docs/ へ隔離した。旧パスのままだとdocs/自体が存在せず書き込みに失敗する。
DOCS_DIR = REPO_ROOT / "archive" / "instructions_history" / "docs"
OUTPUT_PATH = DOCS_DIR / "architecture_facts.json"
TMP_PATH = DOCS_DIR / "architecture_facts.tmp.json"


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


def _route_decorator_fact(decorator: ast.expr) -> dict | None:
    """デコレータ式が `<何か>.get/post/...("パス", ...)` の形であれば
    {base, method, path} を返す。それ以外(通常のデコレータ等)はNone。
    """
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return None
    method = decorator.func.attr.lower()
    if method not in ROUTE_METHODS:
        return None
    path = None
    if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(
        decorator.args[0].value, str
    ):
        path = decorator.args[0].value
    return {"base": ast.unparse(decorator.func.value), "method": method.upper(), "path": path}


def _extract_api_routes(tree: ast.AST) -> list[dict]:
    """関数定義のデコレータからルート定義を機械的に抽出する(FastAPI等の変数名を決め打ちしない)。"""
    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            route = _route_decorator_fact(dec)
            if route is not None:
                routes.append({**route, "function": node.name})
    return routes


def _extract_router_mounts(tree: ast.AST) -> list[dict]:
    """`<何か>.include_router(対象, prefix=..., tags=...)` 呼び出しを機械的に抽出する。
    prefix/tagsはリテラルとして静的に確定できる場合のみ転記し、それ以外はnullのまま残す。
    """
    mounts = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "include_router" or not node.args:
            continue
        prefix = None
        tags = None
        for kw in node.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                prefix = kw.value.value
            elif kw.arg == "tags":
                try:
                    tags = ast.literal_eval(kw.value)
                except (ValueError, SyntaxError):
                    tags = None
        mounts.append({"target": ast.unparse(node.args[0]), "prefix": prefix, "tags": tags})
    return mounts


def extract_file_facts(py_file: Path) -> tuple[dict, list[dict], list[dict]]:
    """1ファイルをASTでパースし、(クラス/関数のファクト, api_routes, router_mounts) を返す。
    パース不能なファイル(SyntaxError等)は例外を送出する(呼び出し元でparse_errorsへ記録)。
    """
    source = py_file.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(py_file))
    display = _display_path(py_file)

    classes = [
        _class_fact(node) for node in tree.body if isinstance(node, ast.ClassDef)
    ]
    functions = [
        _function_fact(node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    file_fact = {
        "path": display,
        "classes": classes,
        "functions": functions,
    }
    api_routes = [{"file": display, **r} for r in _extract_api_routes(tree)]
    router_mounts = [{"file": display, **m} for m in _extract_router_mounts(tree)]
    return file_fact, api_routes, router_mounts


def discover_frontend_pages() -> list[str]:
    """apps/配下とリポジトリ直下のpublic/配下の*.htmlファイルを、除外ルール適用後、
    決定論的な順序(パス文字列の昇順)で返す(SPA用ルーター設定が存在しないため、
    静的HTMLファイルの列挙をもって「ページ構成」のファクトとする)。
    単純なglob列挙のため、Jinjaテンプレートやfetchで取り込まれるHTML断片も
    区別せず含まれる(「どれが実際のページか」の判定は推論にあたるため行わない)。
    """
    pages: list[Path] = []
    for base_dir in FRONTEND_SCAN_DIRS:
        if not base_dir.exists():
            continue
        for html_file in base_dir.rglob("*.html"):
            if _is_excluded(html_file):
                continue
            pages.append(html_file)
    return sorted(_display_path(p) for p in pages)


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
    api_routes: list[dict] = []
    router_mounts: list[dict] = []
    for py_file in py_files:
        try:
            file_fact, routes, mounts = extract_file_facts(py_file)
        except (SyntaxError, UnicodeDecodeError, ValueError) as e:
            parse_errors.append({"path": _display_path(py_file), "error": f"{type(e).__name__}: {e}"})
            continue
        files_facts.append(file_fact)
        api_routes.extend(routes)
        router_mounts.extend(mounts)

    frontend_pages = discover_frontend_pages()

    total_classes = sum(len(f["classes"]) for f in files_facts)
    total_methods = sum(len(c["methods"]) for f in files_facts for c in f["classes"])
    total_functions = sum(len(f["functions"]) for f in files_facts)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "extraction_method": "python ast module (deterministic static analysis; no inference)",
        "scanned_directories": TARGET_DIR_NAMES,
        "excluded_dir_names": sorted(EXCLUDE_DIR_NAMES),
        "files": files_facts,
        "api_routes": api_routes,
        "router_mounts": router_mounts,
        "frontend_pages": frontend_pages,
        "parse_errors": parse_errors,
        "summary": {
            "total_files_scanned": len(py_files),
            "total_files_parsed": len(files_facts),
            "total_parse_errors": len(parse_errors),
            "total_classes": total_classes,
            "total_methods": total_methods,
            "total_module_level_functions": total_functions,
            "total_api_routes": len(api_routes),
            "total_router_mounts": len(router_mounts),
            "total_frontend_pages": len(frontend_pages),
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
    print(
        f"   APIルート{summary['total_api_routes']}件 / "
        f"ルーターマウント{summary['total_router_mounts']}件 / "
        f"フロントエンドページ{summary['total_frontend_pages']}件"
    )
    if facts["parse_errors"]:
        print("⚠️  パースに失敗したファイル:", file=sys.stderr)
        for err in facts["parse_errors"]:
            print(f"   - {err['path']}: {err['error']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
tools/investigate_db_locks.py
================================
DBロック競合(sqlite3.OperationalError: database is locked)の根本原因調査用の
AST解析スクリプト(instructions/304)。

Step 1: packages/shared_core/nazokake_core/database.py を解析し、
        create_async_engine() 呼び出しの引数(timeout/connect_args有無)と、
        PRAGMA実行文(journal_mode=WAL / busy_timeout)の設定状況を抽出する。
Step 2: プロジェクト配下の.pyファイルを走査し、`async with <obj>.begin():`
        トランザクションブロック内で行われるawait呼び出しを列挙し、外部I/O
        (sleep・HTTP・LLM呼び出し等)らしきものを長時間ロックの死角候補として
        ハイライトする。

読み取り専用(ソースコードの変更は一切行わない。ASTによる静的解析のみ)。

使い方:
    uv run python tools/investigate_db_locks.py
"""

from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    sys.stderr.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

# ast.NodeVisitor.generic_visit の再帰は、非常に大きい/深くネストしたモジュール
# (このリポジトリではtools/nazo_agent.py等)でPythonの既定の再帰上限(1000)に
# 到達しうる。1ファイルの規模がスキャン全体を止める理由にはならないため、上限を
# 引き上げつつ、_iter_project_python_files側でもファイル単位でRecursionErrorを
# 捕捉してスキップする(find_transaction_awaits参照)。
sys.setrecursionlimit(10000)

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PY_PATH = (
    BASE_DIR / "packages" / "shared_core" / "nazokake_core" / "database.py"
)

# スキャン対象から除外するディレクトリ(生成物/依存関係/バックアップ)。
_EXCLUDED_DIR_NAMES = {
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".git",
    "build",
    "dist",
}

# 外部I/Oらしき呼び出しを検出するための、呼び出し式(ドット区切り)に含まれると
# 疑わしいキーワード(instructions/304が例示するsleep・外部API通信を主眼とする)。
_SUSPICIOUS_CALL_KEYWORDS = (
    "sleep",
    "http",
    "genai",
    "client",
    "post",
    "request",
    "generate",
    "fetch",
    "ssh",
    "subprocess",
    "gcloud",
)


@dataclass
class EngineCallFinding:
    call_repr: str
    has_timeout_kwarg: bool
    has_connect_args_kwarg: bool
    lineno: int


@dataclass
class PragmaFinding:
    sql: str
    lineno: int
    enclosing_function: str | None


@dataclass
class TransactionAwaitFinding:
    file: str
    transaction_lineno: int
    lineno: int
    call_repr: str
    suspicious: bool


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparse error>"


class _EngineVisitor(ast.NodeVisitor):
    """create_async_engine()呼び出しと、cursor.execute("PRAGMA ...")文を収集する。"""

    def __init__(self) -> None:
        self.engine_calls: list[EngineCallFinding] = []
        self.pragmas: list[PragmaFinding] = []
        self._function_stack: list[str] = []

    def _push_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._push_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._push_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        func_repr = _unparse(node.func)

        if func_repr == "create_async_engine" or func_repr.endswith(
            ".create_async_engine"
        ):
            kwarg_names = {kw.arg for kw in node.keywords if kw.arg}
            self.engine_calls.append(
                EngineCallFinding(
                    call_repr=_unparse(node),
                    has_timeout_kwarg="timeout" in kwarg_names,
                    has_connect_args_kwarg="connect_args" in kwarg_names,
                    lineno=node.lineno,
                )
            )
        elif func_repr.endswith(".execute") and node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(
                first_arg.value, str
            ):
                sql = first_arg.value.strip()
                if sql.upper().startswith("PRAGMA"):
                    self.pragmas.append(
                        PragmaFinding(
                            sql=sql,
                            lineno=node.lineno,
                            enclosing_function=(
                                self._function_stack[-1]
                                if self._function_stack
                                else None
                            ),
                        )
                    )
        self.generic_visit(node)


def analyze_database_module() -> tuple[list[EngineCallFinding], list[PragmaFinding]]:
    """Step 1: database.pyからcreate_async_engine呼び出しとPRAGMA文を抽出する。"""
    source = DATABASE_PY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DATABASE_PY_PATH))
    visitor = _EngineVisitor()
    visitor.visit(tree)
    return visitor.engine_calls, visitor.pragmas


def _iter_project_python_files() -> list[Path]:
    """除外ディレクトリ(.venv/build等)をos.walkの探索段階で剪定しつつ、
    プロジェクト配下の.pyファイル一覧を返す(rglobと違い、除外ディレクトリの
    配下を実際に走査せずスキップできるため大規模な.venv等でも高速)。
    """
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(BASE_DIR):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _EXCLUDED_DIR_NAMES and not d.endswith(".egg-info")
        ]
        for name in filenames:
            if name.endswith(".py"):
                files.append(Path(dirpath) / name)
    return files


def _is_suspicious(call_repr: str) -> bool:
    lowered = call_repr.lower()
    return any(keyword in lowered for keyword in _SUSPICIOUS_CALL_KEYWORDS)


class _TransactionVisitor(ast.NodeVisitor):
    """`async with <expr>.begin():` ブロックを検出し、そのブロック内
    (ネストした関数定義の内部は別スコープとして除外)の全Awaitを列挙する。
    """

    def __init__(self, file_label: str) -> None:
        self.file_label = file_label
        self.findings: list[TransactionAwaitFinding] = []

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        is_transaction_block = any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "begin"
            for item in node.items
        )
        if is_transaction_block:
            for child in ast.walk(node):
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child is not node
                ):
                    continue
                if isinstance(child, ast.Await):
                    call_repr = _unparse(child.value)
                    self.findings.append(
                        TransactionAwaitFinding(
                            file=self.file_label,
                            transaction_lineno=node.lineno,
                            lineno=child.lineno,
                            call_repr=call_repr,
                            suspicious=_is_suspicious(call_repr),
                        )
                    )
        self.generic_visit(node)


def find_transaction_awaits() -> list[TransactionAwaitFinding]:
    """Step 2: プロジェクト全体をスキャンし、`.begin()`トランザクションブロック内の
    await呼び出しを列挙する。"""
    findings: list[TransactionAwaitFinding] = []
    for path in _iter_project_python_files():
        label = str(path.relative_to(BASE_DIR)).replace("\\", "/")
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            visitor = _TransactionVisitor(label)
            visitor.visit(tree)
        except (SyntaxError, UnicodeDecodeError, OSError, RecursionError) as e:
            print(f"⚠️  {label}: 解析をスキップしました({type(e).__name__})", file=sys.stderr)
            continue
        findings.extend(visitor.findings)
    return findings


def main() -> int:
    print("=" * 70)
    print("Step 1: create_async_engine / PRAGMA 設定の解析")
    print(f"対象: {DATABASE_PY_PATH.relative_to(BASE_DIR)}")
    print("=" * 70)
    engine_calls, pragmas = analyze_database_module()

    for call in engine_calls:
        print(f"\n[create_async_engine] line {call.lineno}:")
        print(f"  {call.call_repr}")
        print(f"  timeout引数      : {'あり' if call.has_timeout_kwarg else 'なし'}")
        print(
            f"  connect_args引数 : {'あり' if call.has_connect_args_kwarg else 'なし'}"
        )

    if pragmas:
        print("\n[PRAGMA実行文]")
        for p in pragmas:
            where = f" (関数: {p.enclosing_function})" if p.enclosing_function else ""
            print(f"  line {p.lineno}{where}: {p.sql}")
    else:
        print("\n⚠️  PRAGMA実行文は検出されませんでした。")

    pragma_sqls_compact = [p.sql.upper().replace(" ", "") for p in pragmas]
    has_wal = any("JOURNAL_MODE=WAL" in sql for sql in pragma_sqls_compact)
    busy_timeout_value = None
    for sql in pragma_sqls_compact:
        if sql.startswith("PRAGMABUSY_TIMEOUT="):
            busy_timeout_value = sql.split("=", 1)[1]

    has_engine_timeout = any(c.has_timeout_kwarg for c in engine_calls)

    print("\n--- Step 1 サマリー ---")
    print(
        f"  create_async_engine()へのtimeout引数: "
        f"{'設定あり' if has_engine_timeout else '設定なし'}"
    )
    print(f"  journal_mode=WAL                    : {'設定あり' if has_wal else '設定なし'}")
    print(
        f"  busy_timeout                        : "
        f"{busy_timeout_value + 'ms(設定あり)' if busy_timeout_value else '設定なし'}"
    )

    print("\n" + "=" * 70)
    print("Step 2: トランザクションブロック内のawait(長時間ロックの死角)調査")
    print("=" * 70)
    tx_findings = find_transaction_awaits()

    if not tx_findings:
        print("\n`.begin()`トランザクションブロックは検出されませんでした。")
    else:
        by_file: dict[str, list[TransactionAwaitFinding]] = {}
        for f in tx_findings:
            by_file.setdefault(f.file, []).append(f)

        for file, items in sorted(by_file.items()):
            print(f"\n[{file}]")
            for item in items:
                marker = "🚨 SUSPICIOUS" if item.suspicious else "   info"
                print(
                    f"  [{marker}] transaction@L{item.transaction_lineno} "
                    f"-> await@L{item.lineno}: {item.call_repr}"
                )

    suspicious = [f for f in tx_findings if f.suspicious]

    print("\n--- Step 2 サマリー ---")
    print(f"  検出したトランザクションブロック内await総数: {len(tx_findings)}")
    print(f"  外部I/Oの疑いがあるawait                  : {len(suspicious)}件")

    print("\n" + "=" * 70)
    print("総合レポート")
    print("=" * 70)
    print(
        f"  timeout(create_async_engine引数): "
        f"{'設定あり' if has_engine_timeout else '設定なし'}"
    )
    print(f"  journal_mode=WAL                 : {'設定あり' if has_wal else '設定なし'}")
    print(
        f"  busy_timeout                     : "
        f"{busy_timeout_value + 'ms' if busy_timeout_value else '設定なし'}"
    )
    print(f"  長時間トランザクションの疑いのある箇所: {len(suspicious)}件")
    if suspicious:
        for f in suspicious:
            print(f"    - {f.file}:{f.lineno} ({f.call_repr})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

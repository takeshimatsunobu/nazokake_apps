import asyncio
import datetime
import logging
import os
import sys
import json
import argparse
import ast
import re
import subprocess
import uuid
from pathlib import Path
from dotenv import load_dotenv

# --- SRE絶対防衛線: Norton等のプロキシ干渉をスクリプト起動直後に完全遮断 ---
os.environ["NO_PROXY"] = "api.anthropic.com,github.com"
os.environ["no_proxy"] = "api.anthropic.com,github.com"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from pydantic import BaseModel, ValidationError
import anthropic
import httpx
import psutil


class TokenCircuitBreaker:
    """セッション(デーモン起動中)全体のClaude APIトークン消費を追跡する安全装置。"""

    MAX_TOKENS = 200_000  # 1セッション(デーモン起動中)の安全上限
    used_tokens = 0

    @classmethod
    def add(cls, tokens: int):
        cls.used_tokens += tokens
        if cls.used_tokens > cls.MAX_TOKENS:
            print(
                f"\n🚨 [Circuit Breaker] セッションのトークン消費上限({cls.MAX_TOKENS})を超過しました！"
            )
            print("🚨 APIコスト保護のため、エージェントを強制停止します。")
            sys.exit(1)  # ここはデーモンごと安全に殺すための意図的な exit


# --- ターゲット環境の設定 ---
BASE_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent

# モジュールレベルの定数(MAX_ERROR_LOG_LINES等)がos.getenvで.envの値を読み取れるよう、
# インポート時点で早期に読み込む(main_flow内のload_dotenv呼び出しより前に必要)。
load_dotenv(BASE_DIR / ".env")

# --- V8.9: 標準loggingによるデーモン用ロガー ---
# バックグラウンドタスク(フロントエンド起動等)の監視状態を、コンソールへの
# print()ではなくファイルへ確実に記録する。コンソール用のStreamHandlerは
# 意図的に設定しない(標準出力とのインターリーブ防止)。
log_file = TOOLS_DIR / "audit_reports" / "nazo_agent_daemon.log"
log_file.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("nazo_agent")
logger.setLevel(logging.DEBUG)
logger.propagate = False  # ルートロガー経由でコンソールへ漏れることを防ぐ

if not logger.handlers:
    _file_handler = logging.FileHandler(log_file, encoding="utf-8")
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(_file_handler)

# `python tools/nazo_agent.py` のように直接実行すると sys.path[0] は tools/ 自身に
# なり、`from tools.ast_mapper import ...`(tools を「リポジトリ直下のパッケージ」として
# 参照する絶対import)が ModuleNotFoundError: No module named 'tools' になる。
# リポジトリルートを明示的に sys.path へ追加して解決する。
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# フロントエンドのバックグラウンド起動タスク(fire-and-forget)を GC から守るための保持先。
_bg_tasks: set = set()
# 領域B(アプリ本体)がデフォルト。_route_target_domain() により main_flow 実行時に動的に切り替わる。
TARGET_APP_DIR = BASE_DIR / "apps" / "evaluator"
TARGET_CODE_DIR = "backend"
TARGET_PYTHON = TARGET_APP_DIR / ".venv_ai" / "Scripts" / "python.exe"

# 常駐Web環境(Ollama/Backend/Frontend)専用の固定パス。TARGET_APP_DIR/TARGET_PYTHONとは異なり
# _route_target_domain() によるルーティングの影響を受けない(領域Cにルーティングされても
# ローカルWebサービスは常に領域Bを指す)。
EVALUATOR_APP_DIR = BASE_DIR / "apps" / "evaluator"
EVALUATOR_PYTHON = EVALUATOR_APP_DIR / ".venv_ai" / "Scripts" / "python.exe"


# --- Structured Output Schema ---
class AiderTask(BaseModel):
    file_path: str
    instruction: str


# --- ACD Engine Phase 1 ---
_ACD_NOISE_PATTERNS = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"), "<TIME>"),
    (re.compile(r"0x[0-9a-fA-F]{4,}"), "<HEX>"),
    (
        re.compile(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        ),
        "<UUID>",
    ),
    (re.compile(r"\b(?:pid|PID)[=:\s]?\d+\b"), "<PID>"),
]


def acd_mask_noise(line: str) -> str:
    masked = line
    for pattern, replacement in _ACD_NOISE_PATTERNS:
        masked = pattern.sub(replacement, masked)
    return masked


def acd_phase1_dedup(error_log: str) -> str:
    lines = error_log.split("\n")
    masked_lines = [acd_mask_noise(line) for line in lines]
    result, i = [], 0
    while i < len(lines):
        current = lines[i]
        j = i + 1
        while j < len(lines) and masked_lines[j] == masked_lines[i]:
            j += 1
        result.append(current)
        if j - i > 1:
            result.append(f"[Previous error repeated {j - i - 1} times]")
        i = j
    return "\n".join(result)


# --- ACD Engine Phase 2 & 3 (AST精密抽出) ---
ACD_MAX_SAFE_CHARS = 15000
ACD_MAX_BLOCK_CHARS = 2000
_ACD_LOCATION_RE = re.compile(r"([\w./\\-]+\.py):(\d+)(?::\d+)?:?\s*(.*)")


def acd_extract_symbols(file_path: Path) -> list[str]:
    symbols = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append(node.name)
    except Exception:
        pass
    return symbols


def acd_extract_function_blocks(file_path: Path) -> list[tuple[int, int, str, str]]:
    """AST解析により、ファイル内の関数/クラス単位の(開始行, 終了行, 名前, ソース)を抽出する"""
    blocks = []
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                segment = ast.get_source_segment(source, node)
                if segment is not None:
                    blocks.append(
                        (
                            node.lineno,
                            getattr(node, "end_lineno", node.lineno),
                            node.name,
                            segment,
                        )
                    )
    except Exception:
        pass
    return blocks


def acd_find_enclosing_block(blocks: list[tuple[int, int, str, str]], line_no: int):
    """指定行を含む最小(最も内側)のブロックを返す"""
    candidates = [b for b in blocks if b[0] <= line_no <= b[1]]
    if not candidates:
        return None
    return min(candidates, key=lambda b: b[1] - b[0])


def acd_parse_error_locations(log_text: str) -> list[tuple[str, int, str]]:
    """エラーログから (ファイルパス, 行番号, 該当行全文) を抽出する"""
    findings = []
    for line in log_text.split("\n"):
        m = _ACD_LOCATION_RE.search(line)
        if m:
            findings.append((m.group(1), int(m.group(2)), line.strip()))
    return findings


def _acd_format_block_section(
    header: str, start: int, end: int, source: str, messages: list[str]
) -> str:
    if len(source) > ACD_MAX_BLOCK_CHARS:
        source = source[:ACD_MAX_BLOCK_CHARS] + "\n... (省略) ..."
    unique_messages = "\n".join(f"- {m}" for m in dict.fromkeys(messages))
    return f"### {header} [L{start}-{end}]\n```python\n{source}\n```\n検出された問題:\n{unique_messages}\n"


def acd_ast_compress(
    error_log: str, project_root: Path, max_chars: int = ACD_MAX_SAFE_CHARS
) -> str:
    """
    正規表現/固定行数窓によるラフな切り出しを廃し、AST解析で
    「エラーが発生している関数/クラスのブロックのみ」を正確に抽出して圧縮する。
    ブロックを特定できない行はメッセージ1行のみ残す。全体が安全閾値を超える場合は
    セクション単位で安全に切り捨てる(フェイルセーフ)。
    """
    findings = acd_parse_error_locations(error_log)
    if not findings:
        return error_log[:max_chars]

    block_cache: dict[str, list[tuple[int, int, str, str]]] = {}
    grouped: dict[tuple, dict] = {}
    unresolved: list[str] = []

    for raw_path, line_no, full_line in findings:
        candidate = Path(raw_path)
        full_path = candidate if candidate.is_absolute() else project_root / candidate
        key_path = str(full_path)
        if key_path not in block_cache:
            block_cache[key_path] = (
                acd_extract_function_blocks(full_path) if full_path.exists() else []
            )
        block = acd_find_enclosing_block(block_cache[key_path], line_no)
        if block is None:
            unresolved.append(full_line)
            continue
        group_key = (raw_path, block[0], block[1], block[2])
        entry = grouped.setdefault(group_key, {"source": block[3], "messages": []})
        entry["messages"].append(f"L{line_no}: {full_line}")

    sections = [
        _acd_format_block_section(
            f"{raw_path} :: {name}()", start, end, data["source"], data["messages"]
        )
        for (raw_path, start, end, name), data in grouped.items()
    ]
    if unresolved:
        sections.append(
            "### その他(関数特定不可)\n"
            + "\n".join(f"- {m}" for m in dict.fromkeys(unresolved))
        )

    result_parts, total, omitted = [], 0, 0
    for section in sections:
        if total + len(section) > max_chars:
            omitted += 1
            continue
        result_parts.append(section)
        total += len(section)

    result = "\n".join(result_parts)
    if omitted:
        result += f"\n... ({omitted} 件のセクションを安全閾値超過のため省略) ..."
    return result


def acd_ast_context_for_file(deduped_log: str, target_file: Path) -> str:
    """指定ファイルに関するエラーのみ、AST抽出したブロック単位のコンテキストを返す(Phase 3用)"""
    target_name = target_file.name
    findings = [
        (path, line_no, full_line)
        for path, line_no, full_line in acd_parse_error_locations(deduped_log)
        if Path(path).name == target_name
    ]
    if not findings:
        return ""

    blocks = acd_extract_function_blocks(target_file) if target_file.exists() else []
    grouped: dict[tuple, dict] = {}
    unresolved: list[str] = []
    for _, line_no, full_line in findings:
        block = acd_find_enclosing_block(blocks, line_no)
        if block is None:
            unresolved.append(full_line)
            continue
        key = (block[0], block[1], block[2])
        entry = grouped.setdefault(key, {"source": block[3], "messages": []})
        entry["messages"].append(f"L{line_no}: {full_line}")

    sections = [
        _acd_format_block_section(
            f"{name}()", start, end, data["source"], data["messages"]
        )
        for (start, end, name), data in grouped.items()
    ]
    if unresolved:
        sections.append(
            "### その他(関数特定不可)\n"
            + "\n".join(f"- {m}" for m in dict.fromkeys(unresolved))
        )
    return "\n".join(sections)


def build_static_context() -> Path:
    print(
        "\n🔍 [Pre-processing] 対象領域のASTスキャンによる独自要約マップを生成します..."
    )
    target_dir = TARGET_APP_DIR / TARGET_CODE_DIR
    lines = ["# プロジェクト対象領域の要約マップ (AST抽出)"]
    for py_file in target_dir.rglob("*.py"):
        if ".venv" in py_file.parts or "node_modules" in py_file.parts:
            continue
        symbols = acd_extract_symbols(py_file)
        if symbols:
            lines.append(f"- {py_file.relative_to(target_dir)}: {', '.join(symbols)}")
    audit_dir = TOOLS_DIR / "audit_reports"
    audit_dir.mkdir(exist_ok=True)
    out_file = audit_dir / "static_context.md"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ 独自要約マップ生成完了 -> {out_file}")
    return out_file


# --- V8.5 One-Command Boot (Pre-flight) ---
async def check_http_alive(url: str, timeout: float = 2.0) -> bool:
    """汎用ヘルスチェック（200系レスポンスで生存判定）"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            return response.status_code == 200
    except Exception:
        return False


async def check_ollama() -> bool:
    """Ollamaサーバーのヘルスチェック"""
    return await check_http_alive("http://127.0.0.1:11434/api/tags")


def kill_process_by_port(port: int) -> list[str]:
    """指定ポートをLISTENしているプロセスを検出し、Gracefulに終了する(ゾンビプロセス対策)。

    health_urlが応答しないにもかかわらずポートを掴んだままの子プロセス(クラッシュ後の
    残骸等)が残ると、後続のPopenがアドレス使用中で失敗し続ける。起動直前にこれを
    自動的に一掃する。psutilによるクロスプラットフォーム実装(Windows固有の
    netstat/taskkillへの依存を排除)。まずterminate()で穏やかな終了を試み、
    タイムアウトした場合のみkill()で強制終了する。OSの権限モデルにより対象プロセスの
    情報取得・終了操作が拒否される場合(psutil.AccessDenied)や、対象プロセスが
    スキャン後に既に終了していた場合(psutil.NoSuchProcess)は、それぞれ個別に捕捉して
    警告ログを出力し、システムをクラッシュさせず後続処理へ安全に引き継ぐ
    (ベストエフォートで、終了させたPIDのリストを返す)。
    """
    killed: list[str] = []
    pids: set[int] = set()
    try:
        for conn in psutil.net_connections(kind="inet"):
            if (
                conn.status == psutil.CONN_LISTEN
                and conn.laddr
                and conn.laddr.port == port
                and conn.pid
            ):
                pids.add(conn.pid)
    except psutil.AccessDenied:
        print(
            f"⚠️ [kill_process_by_port] 権限不足のため、ポート{port}の接続一覧を取得できませんでした。"
        )
        return killed
    except Exception as e:
        print(f"⚠️ [kill_process_by_port] 接続一覧の取得中にエラーが発生しました: {e}")
        return killed

    for pid in pids:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except psutil.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3.0)
            killed.append(str(pid))
        except psutil.NoSuchProcess:
            print(
                f"   ⚠️ [kill_process_by_port] プロセス{pid}は既に存在しないためスキップしました。"
            )
        except psutil.AccessDenied:
            print(
                f"   ⚠️ [kill_process_by_port] 権限不足のためプロセス{pid}の終了をスキップしました。"
            )
        except Exception as e:
            print(
                f"   ⚠️ [kill_process_by_port] プロセス{pid}の終了中にエラーが発生しました: {e}"
            )

    return killed


# _ensure_service_alive の各サービス(log_path単位)に対する非同期ロック。
# フロントエンドはfire-and-forgetタスクとして起動されるため、Post-flightで
# startup_local_services() が再度呼ばれた際に「前回起動分のポーリングがまだ
# 終わっていない」まま同じlog_pathへ二重にopen("w")/Popenするレースがあり得る。
# サービス単位で直列化し、ファイル破損・ポートの奪い合いを防ぐ。
_service_locks: dict[str, asyncio.Lock] = {}


def _get_service_lock(key: str) -> asyncio.Lock:
    lock = _service_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _service_locks[key] = lock
    return lock


async def _ensure_service_alive(
    name: str,
    emoji: str,
    health_url: str,
    start_cmd: list[str],
    start_cwd: Path,
    already_ok_msg: str,
    log_path: Path,
    extra_env: dict | None = None,
    retries: int = 15,
    interval: float = 2.0,
    kill_port: int | None = None,
) -> None:
    """汎用: 生存確認 → (必要ならゾンビ掃除) → 停止していればバックグラウンド起動 → ポーリング → 失敗時警告

    子プロセスの標準出力/エラーはlog_pathに保存する(過去にDEVNULLへ捨てていたため、
    UnicodeEncodeError等の実クラッシュ原因が一切見えず診断に手動再現が必要だった)。
    kill_port を指定すると、起動前に対象ポートを掴んでいるゾンビプロセスを強制終了する
    (Ollamaのような長寿命の外部サービスには絶対に使わないこと。Backend/Frontendのような
    このスクリプト自身が管理するサービス専用)。
    """
    # V8.9: バックグラウンドタスク(フロントエンドのfire-and-forget起動等)が
    # メインフローと同時に標準出力へ書き込むと、ターミナル表示が非同期にインター
    # リーブされ崩れる。進行状況・結果・警告はすべて log_path(ファイル)側のみへ
    # 記録し、コンソールへは出力しない。
    async with _get_service_lock(str(log_path)):
        if await check_http_alive(health_url):
            return
        try:
            if kill_port is not None:
                kill_process_by_port(kill_port)

            creationflags = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            ) | getattr(subprocess, "DETACHED_PROCESS", 8)
            env = os.environ.copy()
            if extra_env:
                env.update(extra_env)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as log_file:
                subprocess.Popen(
                    start_cmd,
                    cwd=str(start_cwd),
                    env=env,
                    creationflags=creationflags,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
            for _ in range(retries):
                await asyncio.sleep(interval)
                if await check_http_alive(health_url):
                    break
        except Exception as e:
            # NOTE: SystemExit/KeyboardInterruptはBaseExceptionのサブクラスであり
            # Exceptionを継承しないため、この except では捕捉されない(意図的に安全)。
            # コンソールには出さず、log_path側にのみ例外内容を記録する(診断情報を失わない)。
            # 同じlog_pathへの書き込みは上の _get_service_lock により直列化されているため、
            # このappendが他の呼び出しのPopen出力と競合することはない。
            try:
                with open(log_path, "a", encoding="utf-8") as log_file:
                    log_file.write(f"\n[nazo_agent] {name} 自動起動エラー: {e}\n")
            except Exception:
                pass


def _route_target_domain(instruction: str) -> tuple[Path, str, Path]:
    """ユーザーの指示からターゲット領域(ドメイン)と、そのvenv Pythonを自動判定する"""
    instruction_lower = instruction.lower()

    # 領域C (バッチ工場) のキーワード
    batch_keywords = ["バッチ", "工場", "batch", "factory", "パイプライン", "unsloth"]
    if any(kw in instruction_lower for kw in batch_keywords):
        print(
            "🧭 [Router] ターゲット領域を『バッチ工場 (apps/batch_factory)』に設定しました。"
        )
        target_dir = BASE_DIR / "apps" / "batch_factory"
        return (
            target_dir,
            "batch",
            target_dir / ".venv_train" / "Scripts" / "python.exe",
        )

    # デフォルトは 領域B (アプリ本体)
    print("🧭 [Router] ターゲット領域を『アプリ本体 (apps/evaluator)』に設定しました。")
    target_dir = BASE_DIR / "apps" / "evaluator"
    return (target_dir, "backend", target_dir / ".venv_ai" / "Scripts" / "python.exe")


async def startup_local_services():
    """V8.8: ローカルインフラの自動監査と起動（Ollama + Backend + Frontend）"""
    print("\n🔍 [Pre-flight] ローカル開発環境のインフラ監査を開始します...")

    # Windows上の子プロセスはcp932コンソールにデフォルトなるため、rich等の絵文字出力で
    # UnicodeEncodeErrorを起こす。nazo_agent.py自身のUTF-8設定は子プロセスに伝播しないため明示する。
    utf8_env = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    log_dir = TOOLS_DIR / "audit_reports"

    await _ensure_service_alive(
        name="Ollama",
        emoji="🦙",
        health_url="http://127.0.0.1:11434/api/tags",
        start_cmd=["ollama", "serve"],
        start_cwd=BASE_DIR,
        already_ok_msg="Ollama は既に稼働しています (Port 11434 OK)。",
        log_path=log_dir / "service_ollama.log",
        extra_env=utf8_env,
    )

    # 注: .venv_ai/Scripts/fastapi.exe はvenvリロケートの影響で機能不全のため使わず、
    # 常に python.exe -m fastapi 経由で起動する。
    # オートヒール対応: dev モードにより、Aiderのコード修正を即座にホットリロードさせる
    backend_cmd = [
        str(EVALUATOR_PYTHON),
        "-m",
        "fastapi",
        "dev",
        "backend/main.py",
        "--port",
        "7800",
    ]
    await _ensure_service_alive(
        name="Backend (FastAPI)",
        emoji="⚙️",
        health_url="http://127.0.0.1:7800/api/health",
        start_cmd=backend_cmd,
        start_cwd=EVALUATOR_APP_DIR,
        already_ok_msg="Backend は既に稼働しています (Port 7800 OK)。",
        log_path=log_dir / "service_backend.log",
        extra_env=utf8_env,
        kill_port=7800,
    )

    # フロントエンドは開発用プレビューであり、監査(Phase1)・Aider自動修正(Phase3)の
    # どちらにも必須ではない。Norton等のローカルセキュリティソフトが127.0.0.1への
    # HTTP接続をブロックする既知の事例があり、その場合 _ensure_service_alive の
    # ポーリングが最大30秒待たされてパイプライン全体が足止めされていた。
    # fire-and-forgetタスクとして起動し、結果を待たずに本編へ進む(フォールトトレラント化)。
    frontend_cmd = [str(EVALUATOR_PYTHON), "dev_server.py", "7300"]
    frontend_cwd = EVALUATOR_APP_DIR / "frontend" / "public"

    def _on_frontend_task_done(task: asyncio.Task) -> None:
        _bg_tasks.discard(task)
        if task.cancelled():
            logger.info("[Frontend] バックグラウンド起動タスクはキャンセルされました。")
            return
        exc = task.exception()
        if exc:
            logger.error(
                f"[Frontend] バックグラウンド起動タスクで例外が発生しました(無視して続行): {exc}"
            )

    frontend_task = asyncio.create_task(
        _ensure_service_alive(
            name="Frontend (dev_server)",
            emoji="🖥️",
            health_url="http://127.0.0.1:7300/",
            start_cmd=frontend_cmd,
            start_cwd=frontend_cwd,
            already_ok_msg="Frontend は既に稼働しています (Port 7300 OK)。",
            log_path=log_dir / "service_frontend.log",
            extra_env=utf8_env,
            retries=5,
            interval=1.0,  # 必須サービスではないため待機を短縮
            kill_port=7300,
        )
    )
    _bg_tasks.add(frontend_task)
    frontend_task.add_done_callback(_on_frontend_task_done)

    print("✅ Pre-flight 監査完了。パイプライン本編へ移行します。\n")


# --- Observability (可観測性) ヘルパー ---
async def _progress_dots(message: str, stop_event: asyncio.Event):
    """V8.7 確実なプログレス表示（ドットを打つ）"""
    print(f"   ⏳ {message}", end="", flush=True)
    try:
        while not stop_event.is_set():
            print(".", end="", flush=True)
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        pass
    finally:
        print(" 完了！")


# --- Phase 0 (Ruffによるネイティブ事前自動修復) ---
async def phase0_ruff_autofix() -> None:
    """未使用importやフォーマット違反等のトイルを、LLM推論(Phase 2)前にPythonネイティブで事前消滅させる。

    ruffの修復結果はlogger.debugにのみ記録し、標準出力やPhase 1のメインエラーログ
    (LLMへ渡される成果物)には一切含めない(サイレント実行)。
    """
    target_dir = TARGET_CODE_DIR
    commands = [
        ["uv", "run", "ruff", "check", "--fix", target_dir],
        ["uv", "run", "ruff", "format", target_dir],
    ]
    for cmd in commands:
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(TARGET_APP_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            output = (
                stdout.decode("utf-8", errors="replace")
                + "\n"
                + stderr.decode("utf-8", errors="replace")
            ).strip()
            if output:
                logger.debug(f"[Phase 0 / Ruff Autofix] {' '.join(cmd)}:\n{output}")
        except Exception as e:
            logger.error(f"[Phase 0 / Ruff Autofix] 実行エラー ({' '.join(cmd)}): {e}")


# --- Cognitive Load Auditor (Feature 2.1) ---
# LLMへ渡すコンテキスト(エラーログ・ASTマップ等)が肥大化すると、推論の質が落ちる
# (ハルシネーション)だけでなく無駄なAPI課金も発生する。閾値超過時は推論そのものを
# ブロックし、タスク分割を促すフェイルセーフ("Stop & Split")として機能する。
# 環境ごとに閾値を調整できるよう、.env/環境変数から上書き可能にする
# (未設定時はそれぞれ300行・40000文字をデフォルト値とする)。
MAX_ERROR_LOG_LINES = int(
    os.getenv("MAX_ERROR_LOG_LINES", "300")
)  # エラーログの許容行数
MAX_TOTAL_CONTEXT_CHARS = int(
    os.getenv("MAX_TOTAL_CONTEXT_CHARS", "40000")
)  # プロンプト全体の許容文字数


class CognitiveLoadExceededError(Exception):
    """認知負荷(エラーログ行数・プロンプト文字数)が閾値を超過したことを示す例外。

    sys.exit(1)によるプロセス即死ではなく、呼び出し元(main_flow)が捕捉して
    警告を出力した上でGraceful Shutdown(タスクのスキップ)へ落とし込むために使う。
    """


def check_cognitive_load(
    text: str, max_lines: int | None = None, max_chars: int | None = None
) -> tuple[bool, str]:
    """入力テキストの行数・文字数を計算し、認知負荷が許容範囲内かを判定する。

    max_lines / max_chars のうち指定された項目のみを検査する(両方指定も可)。
    戻り値: (許容範囲内か, 判定内容を示す説明文字列)
    """
    line_count = text.count("\n") + 1
    char_count = len(text)

    violations = []
    if max_lines is not None and line_count > max_lines:
        violations.append(f"行数 {line_count} 行 (上限 {max_lines} 行)")
    if max_chars is not None and char_count > max_chars:
        violations.append(f"文字数 {char_count} 文字 (上限 {max_chars} 文字)")

    if violations:
        return False, " / ".join(violations)
    return True, f"行数 {line_count} 行・文字数 {char_count} 文字 (許容範囲内)"


# --- Dead Letter Queue (Feature 4.x) ---
_PII_PATTERNS = [
    # メールアドレス
    (re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"), "[EMAIL MASKED]"),
    # クレデンシャル/APIキーの典型パターン(sk-... 形式)
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "[CREDENTIAL MASKED]"),
    # Bearerトークン
    (re.compile(r"Bearer\s+[a-zA-Z0-9\-._~+/]+=*"), "[CREDENTIAL MASKED]"),
    # 電話番号らしき連続した数字パターン(2〜4桁-2〜4桁-4桁)
    (re.compile(r"\d{2,4}-\d{2,4}-\d{4}"), "[NUMBER MASKED]"),
]


def sanitize_pii(text: str) -> str:
    """文字列中の機密情報(メールアドレス・APIキー/クレデンシャル・電話番号らしき
    数字パターン)を正規表現で検知し、[XXX MASKED]形式でマスキングする。

    デッドレター(DLQ)にエラーメッセージや会話履歴をプレーンテキストで保存する際、
    機密情報がそのまま平文で記録・漏洩することを防ぐための軽量なサニタイズ処理。
    文字列でない入力は安全に文字列へキャストしてから処理する。
    """
    if not isinstance(text, str):
        text = str(text)
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _write_dead_letter(
    *,
    target_file: str | None,
    system_prompt,
    messages: list,
    final_error: str,
    raw_response: str,
) -> Path:
    """自己修正ループが最大リトライ回数に達し縮退運転へ移行する際、失敗時点の
    全文脈(システムプロンプト・会話履歴・最終エラー・Claudeの生の応答)を
    tools/audit_reports/dead_letters/ 配下へ構造化JSONとして保存する。
    なぜ自己修正しきれなかったかを事後分析できるようにする可観測性強化。

    書き込み前に sanitize_pii で全文字列値をマスキングし、メールアドレスや
    APIキー等の機密情報がDLQへ平文で漏洩することを防ぐ(Epic 4 - 追加課題K)。
    """
    dead_letter_dir = TOOLS_DIR / "audit_reports" / "dead_letters"
    dead_letter_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now()
    dead_letter_path = (
        dead_letter_dir
        / f"dead_letter_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    )

    def _sanitize_jsonable(obj):
        """SDKオブジェクト(pydanticモデル等)をJSON化可能な形へ再帰的に変換しつつ、
        文字列値には sanitize_pii を適用してPIIをマスキングした安全なペイロードを
        再構築する。
        """
        if hasattr(obj, "model_dump"):
            return _sanitize_jsonable(obj.model_dump())
        if isinstance(obj, dict):
            return {k: _sanitize_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_sanitize_jsonable(v) for v in obj]
        if isinstance(obj, str):
            return sanitize_pii(obj)
        if obj is None or isinstance(obj, (int, float, bool)):
            return obj
        return sanitize_pii(str(obj))

    payload = {
        "timestamp": now.isoformat(),
        "target_file": target_file,
        "system_prompt": _sanitize_jsonable(system_prompt),
        "messages": _sanitize_jsonable(messages),
        "final_error": sanitize_pii(final_error),
        "raw_response": sanitize_pii(raw_response),
    }
    with open(dead_letter_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return dead_letter_path


# --- Phase 1 & 4 ---
async def run_linter(tool_name: str) -> str:
    if tool_name == "mypy":
        # dmypy(デーモン)経由で実行し、mypy起動時の型スタブ再解析コスト
        # (プロセス起動ごとのコンテキストスイッチ)を回避する。デーモンが
        # 未起動の場合は `run` が自動的に起動する。
        cmd = [str(TARGET_PYTHON), "-m", "mypy.dmypy", "run", "--", TARGET_CODE_DIR]
    else:
        args = [TARGET_CODE_DIR]
        if tool_name == "ruff":
            # --extend-select S,C90: セキュリティ(S)・複雑度(C90)を段階的に追加。
            # 複雑度エラーが多発する場合は "C90" をここから外すだけで一時的に無効化できる。
            args = ["check", "--extend-select", "S,C90", TARGET_CODE_DIR]
        cmd = [str(TARGET_PYTHON), "-m", tool_name] + args
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(TARGET_APP_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60.0)
        except asyncio.TimeoutError:
            process.kill()
            return f"### ツール: {tool_name.upper()} (🚨 タイムアウト)\n```text\nプロセスがハングアップしました。\n```\n"
        output = (
            stdout.decode("utf-8", errors="replace")
            + "\n"
            + stderr.decode("utf-8", errors="replace")
        ).strip()
        if not output:
            output = "出力なし"
        status = (
            "✅ Success"
            if process.returncode == 0
            else f"⚠️ Exited with code {process.returncode}"
        )
        return f"### ツール: {tool_name.upper()} ({status})\n```text\n{output}\n```\n"
    except Exception as e:
        return (
            f"### ツール: {tool_name.upper()} (🚨 実行エラー)\n```text\n{str(e)}\n```\n"
        )


async def phase1_audit(is_final=False) -> Path:
    phase_name = "Phase 4 最終再監査" if is_final else "Phase 1 現状監査"
    print(
        f"\n🔍 [{phase_name}] ターゲット環境 ({TARGET_APP_DIR.name}/{TARGET_CODE_DIR}) の静的解析を開始します..."
    )
    if not TARGET_PYTHON.exists():
        print(f"🚨 致命的エラー: Python環境が見つかりません: {TARGET_PYTHON}")
        sys.exit(1)
    tools = ["ruff", "mypy"]
    report_lines = [
        "# 🔍 統合静的解析ファクトレポート",
        f"ターゲット: {TARGET_APP_DIR.name}/{TARGET_CODE_DIR}",
        "---",
        "",
    ]
    tasks = [run_linter(tool) for tool in tools]
    results = await asyncio.gather(*tasks)
    for tool, result in zip(tools, results):
        print(f"✅ {tool.upper()} の解析が完了しました。")
        report_lines.append(result)
    audit_dir = TOOLS_DIR / "audit_reports"
    audit_dir.mkdir(exist_ok=True)
    out_file = audit_dir / ("final_error_log.txt" if is_final else "error_log.txt")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"🎉 {phase_name}完了 -> {out_file}")
    return out_file


# --- Phase 2 ---
async def phase2_claude_translation(
    user_instruction: str, error_log_path: Path
) -> dict:
    """Claude API による「AST置換指示」への翻訳・分割。

    従来は自然言語でJSON出力を要求し、応答テキストからMarkdownフェンスを
    手動で除去してjson.loadsする防御的パースに依存していた。tools パラメータに
    tools.ast_modifier.AstModificationInstruction と同一のスキーマ(model_json_schema())
    を関数(Tool)として定義し、tool_choiceでその呼び出しを強制することで、
    解説文やMarkdown装飾が混入する余地をAPIレベルで排除する。
    """
    print(
        "\n🔍 [Phase 2] Claude API による「AST置換指示」への翻訳・分割を開始します..."
    )
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    with open(error_log_path, "r", encoding="utf-8") as f:
        raw_error_log = f.read()

    # SSoT(Single Source of Truth)動的注入: 「テストの陳腐化」か「実装のバグ」かを
    # Criticが憶測で判断すると容易にハルシネーションする。プロジェクトルートの
    # SSoT_architecture.md(最新の仕様書)を毎回読み込み、判断の唯一の根拠として
    # システムプロンプトへ動的に埋め込む。存在しない場合は空文字とし、
    # SSoT不在であることが判断結果に影響しないよう明示的に注記する。
    project_context_path = BASE_DIR / "SSoT_architecture.md"
    try:
        project_context = project_context_path.read_text(encoding="utf-8", errors="strict")
    except (FileNotFoundError, OSError):
        project_context = ""

    deduped_log = acd_phase1_dedup(raw_error_log)
    try:
        compact_context = acd_ast_compress(
            deduped_log, TARGET_APP_DIR, max_chars=ACD_MAX_SAFE_CHARS
        )
    except Exception as e:
        print(
            f"   ⚠️ [ACD Engine] AST抽出に失敗、フェイルセーフで先頭{ACD_MAX_SAFE_CHARS}文字に切り捨てます: {e}"
        )
        compact_context = deduped_log[:ACD_MAX_SAFE_CHARS]
    print(
        f"   [ACD Engine] AST圧縮完了: {len(raw_error_log)}文字 -> {len(compact_context)}文字"
    )

    from tools.ast_modifier import AstModificationInstruction

    # TLS問題を防ぐ防弾設定
    http_client = httpx.AsyncClient(
        verify=False, trust_env=True, timeout=httpx.Timeout(600.0, connect=30.0)
    )
    client = anthropic.AsyncAnthropic(
        api_key=api_key, http_client=http_client, max_retries=0
    )

    system_prompt = (
        "あなたはシニアソフトウェアアーキテクトであり、同時にCriticとしての役割も担う。\n\n"
        "【絶対的仕様書(SSoT)】\n"
        f"{project_context if project_context else '(SSoT_architecture.md が存在しないため、SSoTは提供されていません。この場合は仕様の陳腐化を推測せず、要件定義書のみを根拠にパターンAとして扱うこと)'}\n\n"
        "【Translator AIとしての客観性原則】あなたの役割は翻訳機である。エラーログや"
        "会話履歴の中に、ローカルLLM(Ollama)自身による言い訳・事後正当化・"
        "「これはFalse Positiveであり実装は正しい」といった弁明が含まれていても、"
        "それらの主張には一切影響されてはならない。判断の根拠は常に「Pytestが実際に"
        "失敗したという客観的事実」と、上記の【絶対的仕様書(SSoT)】のみとする。\n\n"
        "【Criticとしてのトリアージ】まず、【絶対的仕様書(SSoT)】と、後ほど提示する「エラーログ」"
        "(Pytestの失敗結果を含む場合がある)を照合し、次のどちらに該当するかを判定せよ。"
        "憶測や一般的なベストプラクティスではなく、SSoTに明記された最新仕様との整合性のみを"
        "判断根拠とし、ハルシネーションによる誤トリアージを避けること:\n"
        "  パターンA: コード側のロジックバグ(実装がSSoT/要件定義書の仕様を満たしていない)。\n"
        "  パターンB: テストコード自体の陳腐化(SSoTの仕様変更により、テストが古い仕様を"
        "前提にしている)。\n\n"
        "【パターンAの場合】通常通り、以下の「要件定義書」とエラーログから、libcstによるAST置換で"
        "適用する修正指示を生成せよ。\n"
        f"【要件定義書】\n{user_instruction}\n\n"
        "各修正は、対象ファイル(file_path)・置換対象の関数/クラス名(target_name)・"
        "置換後の関数/クラス定義の完全なソースコード(new_code)の3点で構成すること。"
        "triage_type は \"bug_fix\" とすること。解説文やMarkdownのコードブロック装飾は"
        "一切付けず、必ず submit_ast_modifications ツールの呼び出しのみで結果を提出すること。\n\n"
        "【パターンBの場合】SSoTに明記された最新仕様に合わせて、陳腐化したテストコードを"
        "修正するタスクを生成せよ。修正対象・方法はパターンAと同じ3点"
        "(file_path・target_name・new_code)で構成し、生成する各タスクの triage_type を"
        "必ず \"test_update\" にして submit_ast_modifications ツールで提出すること。"
        "summary フィールドには「⚠️ テストの陳腐化を検知し、修正ドラフトを生成しました。"
        "レビュー・マージは人間が行ってください」という旨を明記せよ"
        "(このタスクは即座に本番ブランチへ適用されず、人間レビュー用の隔離ブランチに"
        "隔離される)。"
    )
    system_blocks = [
        {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
    ]

    # Claude API に渡すツール定義。Pydanticモデル(tools.ast_modifier.AstModificationInstruction)の
    # JSON Schemaをそのまま input_schema へ流用し、Tool Calling強制の出力形式と
    # サーバー側バリデーションの型定義を単一のスキーマ源(Single Source of Truth)に保つ。
    submit_tool = {
        "name": "submit_ast_modifications",
        "description": "監査結果に基づき確定した、libcstによる安全なAST置換指示の一覧を提出する。",
        "input_schema": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": AstModificationInstruction.model_json_schema(),
                },
                "summary": {"type": "string"},
            },
            "required": ["tasks", "summary"],
        },
    }

    # 自己修正ループ(Self-Correction): Pydanticのスキーマ違反を正規表現等で無理に
    # 救済せず、エラー内容をそのままtool_result(is_error=True)としてClaudeへ返し、
    # 正しい型で再出力させる。最大3回試行し、3回連続で失敗した場合のみ、パイプライン
    # 全体を落とさず縮退運転(タスク0件として継続)する。
    MAX_SELF_CORRECTION_RETRIES = 3
    # エラーログ(compact_context)は自己修正リトライの全attemptで不変のまま
    # messages[0]に居座り続けるため、Prompt Cachingの対象として最も効果が高い。
    # 2回目以降のリトライではこのブロックがキャッシュヒットし、トークン消費を抑える。
    error_log_text = f"【エラーログ】\n{compact_context}"
    messages: list = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": error_log_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    ]

    # Cognitive Load Auditor: API呼び出し直前に、実際に送信するプロンプト全体量を検査する。
    prompt_ok, prompt_detail = check_cognitive_load(
        system_prompt + error_log_text, max_chars=MAX_TOTAL_CONTEXT_CHARS
    )
    if not prompt_ok:
        raise CognitiveLoadExceededError(
            f"プロンプト全体が大きすぎます ({prompt_detail})"
        )

    result_json: dict = {"tasks": [], "summary": ""}
    stop_event = asyncio.Event()

    # 進行状況の表示タスク開始 (ドット印字版)
    progress_task = asyncio.create_task(
        _progress_dots("Claude API 思考・翻訳中", stop_event)
    )

    try:
        for attempt in range(1, MAX_SELF_CORRECTION_RETRIES + 1):
            response = await client.messages.create(
                model="claude-sonnet-5",
                max_tokens=8192,
                system=system_blocks,
                messages=messages,
                tools=[submit_tool],
                tool_choice={"type": "tool", "name": "submit_ast_modifications"},
            )

            usage = getattr(response, "usage", None)
            if usage:
                total_tokens = getattr(usage, "input_tokens", 0) + getattr(
                    usage, "output_tokens", 0
                )
                TokenCircuitBreaker.add(total_tokens)

            submit_block = next(
                (
                    b
                    for b in response.content
                    if getattr(b, "type", "") == "tool_use"
                    and b.name == "submit_ast_modifications"
                ),
                None,
            )
            if submit_block is None:
                raise ValueError(
                    "submit_ast_modifications ツールの呼び出しが得られませんでした。"
                )

            messages.append({"role": "assistant", "content": response.content})

            try:
                validated_tasks = []
                for raw_task in submit_block.input.get("tasks", []):
                    validated = AstModificationInstruction(**raw_task)
                    task_dict = validated.model_dump()
                    task_dict["mode"] = "ast_replace"
                    validated_tasks.append(task_dict)
                result_json = {
                    "tasks": validated_tasks,
                    "summary": submit_block.input.get("summary", ""),
                }
                break
            except ValidationError as e:
                print(
                    f"   ⚠️ [Self-Correction {attempt}/{MAX_SELF_CORRECTION_RETRIES}] スキーマ違反を検知しました: {e}"
                )
                if attempt >= MAX_SELF_CORRECTION_RETRIES:
                    print(
                        f"⚠️ 部分的障害: {MAX_SELF_CORRECTION_RETRIES}回の自己修正リトライすべて失敗したため、"
                        "このフェーズの修正をスキップします (縮退運転)。"
                    )
                    raw_tasks_for_error = submit_block.input.get("tasks", [])
                    target_file = (
                        ", ".join(
                            t.get("file_path", "")
                            for t in raw_tasks_for_error
                            if isinstance(t, dict) and t.get("file_path")
                        )
                        or None
                    )
                    dead_letter_path = _write_dead_letter(
                        target_file=target_file,
                        system_prompt=system_blocks,
                        messages=messages,
                        final_error=str(e),
                        raw_response=json.dumps(submit_block.input, ensure_ascii=False),
                    )
                    print(
                        f"   📮 [Dead Letter] 失敗内容を記録しました -> {dead_letter_path}"
                    )
                    result_json = {
                        "tasks": [],
                        "summary": "(自己修正リトライ失敗のため対象なし)",
                    }
                    break
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": submit_block.id,
                                "content": f"指定されたJSONスキーマに違反しています。以下のエラーを修正し、再度出力してください：\n{e}",
                                "is_error": True,
                            }
                        ],
                    }
                )
                continue

        stop_event.set()
        await progress_task

    except Exception as e:
        stop_event.set()
        await progress_task
        print(f"\n🚨 Phase 2 抽出エラー: {str(e)}")
        sys.exit(1)
    finally:
        await http_client.aclose()

    triage_path = TOOLS_DIR / "audit_reports" / "triage_result.json"
    with open(triage_path, "w", encoding="utf-8") as f:
        json.dump(result_json, f, indent=2, ensure_ascii=False)

    tasks = result_json.get("tasks", [])
    print("\n" + "=" * 50)
    print("📋 【Claude 設計翻訳結果（AST置換指令）】")
    print(f" ［修正対象タスク数］: {len(tasks)} 件")
    for idx, task in enumerate(tasks, 1):
        print(f"   {idx}. {task.get('file_path', '不明なパス')}")
        print(f"      対象シンボル: {task.get('target_name', '不明')}")
    print("\n ［実装サマリー］:\n  " + result_json.get("summary", "記述なし"))
    print("=" * 50 + "\n")
    print(f"✅ フェーズ2完了: AST置換指令書を保存しました -> {triage_path}")
    return result_json


def _build_tree_lines(dir_path: Path, prefix: str, lines: list) -> None:
    """dir_path直下を除外ルール適用済みで走査し、tree形式の行をlinesへ追記する再帰ヘルパー。"""
    from tools.extract_source import _is_excluded_dir, _is_excluded_file

    try:
        entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return
    entries = [
        e
        for e in entries
        if not (e.is_dir() and _is_excluded_dir(e.name))
        and not (e.is_file() and _is_excluded_file(e))
    ]
    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}")
        if entry.is_dir():
            extension = "    " if is_last else "│   "
            _build_tree_lines(entry, prefix + extension, lines)


def generate_directory_tree() -> str:
    """apps/, packages/, tools/ 配下のディレクトリツリーを文字列として生成する。

    Tree-based Context アーキテクチャ(Epic 1 FinOps)の中核: フルソースコードダンプを
    Claudeへ送る代わりに、この「地図」だけを渡し、実際に必要なファイルの内容は
    Claude自身がread_file_section等のツールでOn-demandに取得する構成へ移行する。
    除外ルール(仮想環境・生成物ディレクトリ、バイナリ拡張子等)は
    tools/extract_source.py と共通化し、二重管理を避ける。
    """
    from tools.extract_source import TARGET_DIRS

    lines: list = []
    for target in TARGET_DIRS:
        target_dir = BASE_DIR / target
        if not target_dir.is_dir():
            continue
        lines.append(f"{target}/")
        _build_tree_lines(target_dir, "", lines)
    return "\n".join(lines)


# --- Phase 2 (Tool-Augmented) ---
async def phase2_claude_tool_augmented(
    user_instruction: str, error_log_path: Path
) -> dict:
    """Tool-Augmented版Phase 2。

    tools.ast_mapper.get_symbol_definition / tools.file_reader.read_file_section /
    tools.pyright_tool.get_type_info をClaudeに公開し、Claude自身が「双方向推論ループ」で
    自律的にコードを調査してからAiderTask のリストを確定させる。get_type_info はPyrightの
    実診断結果を返すことで、型エラーの推測によるハルシネーション修正を防ぐ。
    最終提出は submit_aider_plan ツールへのtool_choice強制で構造化出力を保証する。
    """
    from tools.ast_mapper import get_symbol_definition
    from tools.file_reader import read_file_section
    from tools.pyright_tool import get_type_info

    print(
        "\n🔍 [Phase 2 / Tool-Augmented] Claude API による自律調査・翻訳を開始します..."
    )
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    with open(error_log_path, "r", encoding="utf-8") as f:
        raw_error_log = f.read()

    deduped_log = acd_phase1_dedup(raw_error_log)
    try:
        compact_context = acd_ast_compress(
            deduped_log, TARGET_APP_DIR, max_chars=ACD_MAX_SAFE_CHARS
        )
    except Exception as e:
        print(
            f"   ⚠️ [ACD Engine] AST抽出に失敗、フェイルセーフで先頭{ACD_MAX_SAFE_CHARS}文字に切り捨てます: {e}"
        )
        compact_context = deduped_log[:ACD_MAX_SAFE_CHARS]

    # TLS問題を防ぐ防弾設定
    http_client = httpx.AsyncClient(
        verify=False, trust_env=True, timeout=httpx.Timeout(600.0, connect=30.0)
    )
    client = anthropic.AsyncAnthropic(
        api_key=api_key, http_client=http_client, max_retries=0
    )

    # Tree-based Context: フルソースコードを送信する代わりに、ディレクトリ構造(地図)だけを
    # 渡す。実際に必要なファイルの内容は、以下のsystem_prompt内の指示に従い、Claude自身が
    # read_file_section等のツールでOn-demandに取得する(Epic 1 FinOps)。
    directory_tree = generate_directory_tree()

    system_prompt = (
        "あなたは冷徹な設計翻訳機であり、シニアソフトウェアアーキテクトです。"
        "以下の「要件定義書」と後ほど提示する「エラーログ」からAiderの修正手順を生成せよ。\n"
        f"【要件定義書】\n{user_instruction}\n\n"
        "【プロジェクトのディレクトリツリー（地図）】\n"
        f"{directory_tree}\n\n"
        "上記はファイル名・ディレクトリ構造のみであり、各ファイルの内容は一切含まれていない。"
        "提供されたエラーログとこのディレクトリツリーを確認し、エラー解決に必要なソースコードは"
        "推測せず、必ず get_symbol_definition / read_file_section ツールを用いて自律的に取得"
        f"してから判断すること。対象領域は{TARGET_APP_DIR / TARGET_CODE_DIR}を基準とする。"
        "型エラー・型不整合が疑われる場合は、推測で修正案を組み立てず、"
        "必ず get_type_info ツールでPyrightの実診断結果を取得してから判断すること。"
        "調査が完了したら必ず submit_aider_plan ツールで最終結果を提出すること。"
    )
    # このsystem_promptは MAX_TURNS 回の自律調査ループ全体で不変のまま毎ターン再送される
    # ため、Prompt Cachingにより2ターン目以降のキャッシュヒットでコストを圧縮する。
    system_blocks = [
        {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
    ]

    # Claude API に渡すツール定義(JSON Schema形式)
    investigation_tools = [
        {
            "name": "get_symbol_definition",
            "description": "シンボル名(関数名またはクラス名の完全一致)から、その定義元のソースコード全文をASTで検索して返す。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "検索する関数名またはクラス名(完全一致)",
                    },
                },
                "required": ["symbol_name"],
            },
        },
        {
            "name": "read_file_section",
            "description": "指定ファイルの特定行範囲を行番号付きで読み込む。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "読み込むファイルのパス",
                    },
                    "start_line": {"type": "integer", "description": "開始行(1始まり)"},
                    "end_line": {
                        "type": "integer",
                        "description": "終了行(1始まり・両端含む)",
                    },
                },
                "required": ["file_path", "start_line", "end_line"],
            },
        },
        {
            "name": "get_type_info",
            "description": "指定ファイルをPyrightで型検査し、実際の型エラー・型不整合の診断結果を返す。推測ではなく実診断に基づいて型修正を判断するために使う。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "型検査するファイルのパス",
                    },
                },
                "required": ["file_path"],
            },
        },
    ]

    # 最終出力スキーマ(既存の AiderTask Pydanticモデルに準拠)。tool_choiceで強制することで
    # Structured Outputを保証し、旧来のMarkdownフェンス除去等の手動パースを不要にする。
    submit_tool = {
        "name": "submit_aider_plan",
        "description": "調査が完了し、Aiderへの修正指令が確定したら、この関数で最終結果を提出する。",
        "input_schema": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": (
                                    "修正対象のファイルパス。必ずリポジトリルート(BASE_DIR)または"
                                    "対象アプリ(TARGET_APP_DIR)からの相対パスで記述すること。"
                                    "絶対パスは使用不可。"
                                ),
                            },
                            "instruction": {"type": "string"},
                        },
                        "required": ["file_path", "instruction"],
                    },
                },
                "summary": {"type": "string"},
            },
            "required": ["tasks", "summary"],
        },
    }

    all_tools = investigation_tools + [submit_tool]
    # エラーログ(compact_context)は MAX_TURNS 回の自律調査ループ全体で不変のまま
    # messages[0]に居座り続けるため、Prompt Cachingの対象として効果が高い。
    error_log_text = f"【エラーログ】\n{compact_context}"
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": error_log_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    ]

    # Cognitive Load Auditor: API呼び出し直前に、実際に送信するプロンプト全体量を検査する。
    prompt_ok, prompt_detail = check_cognitive_load(
        system_prompt + error_log_text, max_chars=MAX_TOTAL_CONTEXT_CHARS
    )
    if not prompt_ok:
        raise CognitiveLoadExceededError(
            f"プロンプト全体が大きすぎます ({prompt_detail})"
        )

    result_json: dict = {}
    stop_event = asyncio.Event()
    progress_task = asyncio.create_task(
        _progress_dots("Claude API 自律調査・翻訳中", stop_event)
    )

    MAX_TURNS = 5
    try:
        for turn in range(1, MAX_TURNS + 1):
            force_final = turn == MAX_TURNS
            response = await client.messages.create(
                model="claude-sonnet-5",
                max_tokens=8192,
                system=system_blocks,
                messages=messages,
                tools=all_tools,
                tool_choice={"type": "tool", "name": "submit_aider_plan"}
                if force_final
                else {"type": "auto"},
            )

            # レスポンスから入力・出力トークンを取得して記録
            usage = getattr(response, "usage", None)
            if usage:
                total_tokens = getattr(usage, "input_tokens", 0) + getattr(
                    usage, "output_tokens", 0
                )
                TokenCircuitBreaker.add(total_tokens)

            submit_block = next(
                (
                    b
                    for b in response.content
                    if getattr(b, "type", "") == "tool_use"
                    and b.name == "submit_aider_plan"
                ),
                None,
            )
            if submit_block is not None:
                raw_tasks = submit_block.input.get("tasks", [])
                validated_tasks = [AiderTask(**t).model_dump() for t in raw_tasks]
                result_json = {
                    "tasks": validated_tasks,
                    "summary": submit_block.input.get("summary", ""),
                }
                break

            if response.stop_reason != "tool_use":
                # ツール未使用のまま終了した場合は、次ターンで最終提出を促す
                messages.append({"role": "assistant", "content": response.content})
                messages.append(
                    {
                        "role": "user",
                        "content": "調査内容をもとに、必ず submit_aider_plan ツールで最終結果を提出してください。",
                    }
                )
                continue

            # 調査ツール呼び出しをPython側で実行し、tool_resultとして履歴に積んで再送する
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if getattr(block, "type", "") != "tool_use":
                    continue
                if block.name == "get_symbol_definition":
                    tool_output = get_symbol_definition(
                        [TARGET_APP_DIR / TARGET_CODE_DIR],
                        block.input.get("symbol_name", ""),
                    )
                elif block.name == "read_file_section":
                    tool_output = read_file_section(
                        block.input.get("file_path", ""),
                        block.input.get("start_line", 1),
                        block.input.get("end_line", 1),
                    )
                elif block.name == "get_type_info":
                    tool_output = get_type_info(block.input.get("file_path", ""))
                else:
                    tool_output = f"Error: 未知のツール '{block.name}' です。"
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tool_output,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        stop_event.set()
        await progress_task

        if not result_json:
            print(
                "\n🚨 Phase 2(Tool-Augmented) 抽出エラー: 最大ターン数内に最終結果が得られませんでした。"
            )
            sys.exit(1)

    except Exception as e:
        stop_event.set()
        await progress_task
        print(f"\n🚨 Phase 2(Tool-Augmented) 抽出エラー: {str(e)}")
        sys.exit(1)
    finally:
        await http_client.aclose()

    triage_path = TOOLS_DIR / "audit_reports" / "triage_result.json"
    with open(triage_path, "w", encoding="utf-8") as f:
        json.dump(result_json, f, indent=2, ensure_ascii=False)

    tasks = result_json.get("tasks", [])
    print("\n" + "=" * 50)
    print("📋 【Claude(Tool-Augmented) 設計翻訳結果（Aiderへの確定指令）】")
    print(f" ［修正対象タスク数］: {len(tasks)} 件")
    for idx, task in enumerate(tasks, 1):
        print(f"   {idx}. {task.get('file_path', '不明なパス')}")
        print(f"      指示: {task.get('instruction', '記述なし')}")
    print("\n ［実装サマリー］:\n  " + result_json.get("summary", "記述なし"))
    print("=" * 50 + "\n")
    print(
        f"✅ フェーズ2(Tool-Augmented)完了: Aiderへの確定指令書を保存しました -> {triage_path}"
    )
    return result_json


# --- Phase 3 ---
IDLE_TIMEOUT_SECONDS = 300.0


async def _drain_stream(
    stream: asyncio.StreamReader, buffer: list, activity: dict
) -> None:
    loop = asyncio.get_running_loop()
    while True:
        line = await stream.readline()
        if not line:
            break
        buffer.append(line)
        activity["last"] = loop.time()


async def run_subprocess_with_idle_timeout(
    process: asyncio.subprocess.Process, idle_timeout: float
):
    stdout_buf = []
    stderr_buf = []
    activity = {"last": asyncio.get_running_loop().time()}

    out_task = asyncio.create_task(_drain_stream(process.stdout, stdout_buf, activity))
    err_task = asyncio.create_task(_drain_stream(process.stderr, stderr_buf, activity))

    while True:
        if process.returncode is not None:
            break
        now = asyncio.get_running_loop().time()
        if now - activity["last"] > idle_timeout:
            process.kill()
            raise asyncio.TimeoutError()
        await asyncio.sleep(1)

    await asyncio.gather(out_task, err_task)
    return b"".join(stdout_buf), b"".join(stderr_buf)


def _resolve_target_file(file_path: str) -> Path | None:
    """LLMが返したfile_pathをゼロトラストで解決する。

    TARGET_APP_DIR起点・BASE_DIR起点の2候補を.resolve()した絶対パスで存在確認し、
    どちらも無ければファイル名一致でBASE_DIR配下を検索する(候補が複数なら曖昧なので不採用)。
    最終的にBASE_DIR配下に封じ込まれていない候補(絶対パス指定やパストラバーサル等)は
    採用しない。
    """
    raw_path = Path(file_path)
    base_resolved = BASE_DIR.resolve()

    resolved: Path | None = None
    for candidate in (TARGET_APP_DIR / raw_path, BASE_DIR / raw_path):
        candidate_resolved = candidate.resolve()
        if candidate_resolved.exists():
            resolved = candidate_resolved
            break

    if resolved is None:
        matches = [m.resolve() for m in BASE_DIR.rglob(raw_path.name)]
        if len(matches) == 1:
            resolved = matches[0]

    if resolved is None:
        return None

    if not resolved.is_relative_to(base_resolved):
        return None

    return resolved


async def phase3_aider_execution(
    tasks: list[dict], deduped_error_log: str, static_context_path: Path
) -> tuple[int, list[str]]:
    print(
        f"\n🔍 [Phase 3] Aider による個別ファイル修正を開始します (対象: {len(tasks)} 件)..."
    )
    if not tasks:
        print("✅ フェーズ3完了: 修正対象タスクが0件のためスキップしました。")
        return 0, []

    clean_env = os.environ.copy()
    clean_env["ANTHROPIC_API_KEY"] = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    clean_env["GEMINI_API_KEY"] = (os.getenv("GEMINI_API_KEY") or "").strip()
    clean_env["PYTHONIOENCODING"] = "utf-8"
    clean_env["PYTHONUTF8"] = "1"
    clean_env["AIDER_VERBOSE"] = "1"
    clean_env["LITELLM_LOG"] = "DEBUG"

    custom_ca_bundle = os.path.expanduser("~/.certs/custom_ca_bundle.pem")
    clean_env["REQUESTS_CA_BUNDLE"] = custom_ca_bundle
    clean_env["SSL_CERT_FILE"] = custom_ca_bundle

    success_count = 0
    failure_count = 0
    successful_files = []

    for idx, task in enumerate(tasks, 1):
        file_path = task.get("file_path", "")
        mode = task.get("mode", "aider")
        instruction = task.get("instruction", "")
        # mode == "ast_replace" (libcstによる決定論的置換)のタスクはtarget_name/new_codeで
        # 完結し、自然言語のinstructionを持たない(Aider専用のレガシーフィールド)。
        # instructionを必須にすると、phase2_claude_translationが生成するast_replaceタスクが
        # 常にここで無条件スキップされてしまうため、aiderモードのみinstructionを必須とする。
        if not file_path or (mode != "ast_replace" and not instruction):
            continue

        resolved_target_file = _resolve_target_file(file_path)
        print("\n" + "=" * 50)
        print(
            f"🛠️  [{idx}/{len(tasks)}] {'AST置換 (libcst)' if mode == 'ast_replace' else 'Aider起動'}: {file_path}"
        )
        print(f"   指示: {instruction}")

        if resolved_target_file is None:
            print(
                f"⚠️ 警告: 対象ファイルが存在しない、または安全な範囲外です。スキップします -> {file_path}"
            )
            failure_count += 1
            print(
                "⚠️ 部分的障害: このファイルの修正をスキップし、後続のタスクを継続します (縮退運転)。"
            )
            continue
        target_file = resolved_target_file

        # --- 報酬ハック防御(Reward Hacking Defense): テストコード自体の直接書き換えを
        # 原則ブロックする。LLMが「テストを通す」という報酬を最短距離で得るために、
        # 実装のバグを直さずテストの期待値やアサーションを書き換えてしまう(テストを
        # 無力化する)局所最適解に陥るのを、決定論的に物理阻止する安全装置。
        # ただし、Phase 2のCriticがSSoT(SSoT_architecture.md)照合の結果、正当な
        # 「テストの陳腐化」と明示的にトリアージした(triage_type == "test_update")タスクに
        # 限り、この防御を素通しする(誤トリアージされた"bug_fix"のままテストファイルを
        # 狙うタスクは、従来通り一律ブロックされ続ける)。
        normalized_path = str(target_file).replace("\\", "/")
        is_test_path = "test_" in normalized_path or "tests/" in normalized_path
        triage_type = task.get("triage_type", "bug_fix")
        if is_test_path and triage_type != "test_update":
            print(
                "⚠️ テストコードの直接書き換えはブロックされました（報酬ハック防御）"
            )
            failure_count += 1
            print(
                "⚠️ 部分的障害: このファイルの修正をスキップし、後続のタスクを継続します (縮退運転)。"
            )
            continue
        if is_test_path and triage_type == "test_update":
            print(
                "⚠️ テストの陳腐化(triage_type=test_update)と判定されたタスクのため、"
                "報酬ハック防御を通過させます(隔離ドラフトブランチでの人間レビューが必須です)。"
            )

        # --- ハイブリッド・ルーティング: mode == "ast_replace" は非決定的なAiderを
        # 一切起動せず、libcstによる決定論的なノード置換(tools/ast_modifier.py)へ委譲する。
        if mode == "ast_replace":
            target_name = task.get("target_name", "")
            new_code = task.get("new_code", "")
            if not target_name or not new_code:
                print(
                    f"⚠️ 警告: ast_replaceモードには target_name/new_code が必須です。スキップします -> {file_path}"
                )
                failure_count += 1
                print(
                    "⚠️ 部分的障害: このファイルの修正をスキップし、後続のタスクを継続します (縮退運転)。"
                )
                continue

            ast_instruction_path = TOOLS_DIR / "audit_reports" / f"_ast_task_{idx}.json"
            ast_instruction_path.parent.mkdir(parents=True, exist_ok=True)
            with open(ast_instruction_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "file_path": str(target_file),
                        "target_name": target_name,
                        "new_code": new_code,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

            start_time = asyncio.get_running_loop().time()
            try:
                result = subprocess.run(
                    [
                        "uv",
                        "run",
                        "python",
                        "tools/ast_modifier.py",
                        str(ast_instruction_path),
                    ],
                    cwd=str(BASE_DIR),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="strict",
                )
                elapsed = asyncio.get_running_loop().time() - start_time
                print(f"⏱️ 処理時間: {elapsed:.1f}秒 ({file_path})")
                output = (result.stdout + "\n" + result.stderr).strip()

                if result.returncode == 0:
                    print(f"✅ 完了(AST置換): {file_path}")
                    if output:
                        logger.debug(f"AST Replace Success Output:\n{output}")
                    success_count += 1
                    successful_files.append(str(target_file))
                else:
                    print(
                        f"⚠️ AST置換が異常終了しました (code={result.returncode}): {file_path}"
                    )
                    if output:
                        print(f"```text\n{output}\n```\n")
                        logger.error(f"AST Replace Error Output:\n{output}")
                    failure_count += 1
                    print(
                        "⚠️ 部分的障害: このファイルの修正をスキップし、後続のタスクを継続します (縮退運転)。"
                    )
            except Exception as e:
                elapsed = asyncio.get_running_loop().time() - start_time
                print(f"⏱️ 処理時間: {elapsed:.1f}秒 ({file_path})")
                print(f"🚨 実行エラー ({file_path}): {type(e).__name__} - {str(e)}")
                failure_count += 1
                print(
                    "⚠️ 部分的障害: このファイルの修正をスキップし、後続のタスクを継続します (縮退運転)。"
                )
            finally:
                ast_instruction_path.unlink(missing_ok=True)
            continue

        # --- 従来フロー: mode == "aider" または mode 未指定時のフォールバック ---
        try:
            context_snippet = acd_ast_context_for_file(deduped_error_log, target_file)
        except Exception as e:
            print(f"   ⚠️ [ACD Engine] AST抽出に失敗しました({file_path}): {e}")
            context_snippet = ""

        full_message = instruction
        if context_snippet:
            full_message += "\n\n【関連エラーファクト(抜粋)】\n" + context_snippet

        cmd = [
            "aider",
            "--yes-always",
            "--no-verify-ssl",
            "--no-gitignore",
            "--model",
            "anthropic/claude-sonnet-5",
            "--thinking-tokens",
            "0",
            "--message",
            full_message,
            "--map-tokens",
            "0",
            "--no-auto-commits",
            "--cache-prompts",
            "--cache-keepalive-pings",
            "2",
            "--read",
            str(static_context_path),
            str(target_file),
        ]

        process = None
        start_time = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(TARGET_APP_DIR),
                env=clean_env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            process.stdin.close()
            start_time = asyncio.get_running_loop().time()

            stdout, stderr = await run_subprocess_with_idle_timeout(
                process, idle_timeout=IDLE_TIMEOUT_SECONDS
            )
            output = (
                stdout.decode("utf-8", errors="replace")
                + "\n"
                + stderr.decode("utf-8", errors="replace")
            ).strip()

            elapsed = asyncio.get_running_loop().time() - start_time
            print(f"⏱️ 処理時間: {elapsed:.1f}秒 ({file_path})")

            if process.returncode == 0:
                print(f"✅ 完了: {file_path}")
                if output:
                    logger.debug(f"Aider Success Output:\n{output}")
                success_count += 1
                successful_files.append(str(target_file))
            else:
                print(
                    f"⚠️ Aiderが異常終了しました (code={process.returncode}): {file_path}"
                )
                if output:
                    print(f"```text\n{output}\n```\n")
                    logger.error(f"Aider Error Output:\n{output}")
                failure_count += 1
                print(
                    "⚠️ 部分的障害: このファイルの修正をスキップし、後続のタスクを継続します (縮退運転)。"
                )
                continue
        except asyncio.TimeoutError:
            process.kill()
            elapsed = asyncio.get_running_loop().time() - start_time
            print(f"⏱️ 処理時間: {elapsed:.1f}秒 ({file_path})")
            print(
                f"🚨 アイドル・タイムアウト: {file_path} の修正で{int(IDLE_TIMEOUT_SECONDS)}秒間出力が完全に途絶えたため強制終了しました。"
            )
            failure_count += 1
            print(
                "⚠️ 部分的障害: このファイルの修正をスキップし、後続のタスクを継続します (縮退運転)。"
            )
            continue
        except Exception as e:
            if process is not None and process.returncode is None:
                process.kill()
            elapsed = (
                asyncio.get_running_loop().time() - start_time if start_time else 0
            )
            print(f"⏱️ 処理時間: {elapsed:.1f}秒 ({file_path})")
            print(f"🚨 実行エラー ({file_path}): {type(e).__name__} - {str(e)}")
            failure_count += 1
            print(
                "⚠️ 部分的障害: このファイルの修正をスキップし、後続のタスクを継続します (縮退運転)。"
            )
            continue

    print(
        f"\n🎉 フェーズ3完了: 成功 {success_count} 件 / 失敗 {failure_count} 件 (全 {len(tasks)} 件)"
    )
    return success_count, successful_files


def _has_staged_changes(cwd: Path, files: list[str]) -> bool:
    """指定ファイル群に、コミット可能なステージ済み変更(新規/変更/削除)があるかを判定する。

    `git diff --cached --quiet` は多くの場合これで十分だが、新規追跡ファイル
    (直前の `git add` で初めてインデックスに入ったファイル)を含むケースを
    確実に扱うため、`git status --porcelain --` の各行の先頭1文字(インデックス側の
    ステータス)を直接判定する: 空白(' ')は未ステージ、'?' は完全未追跡を意味し、
    それ以外(A/M/D/R/C 等)はステージ済み変更が存在することを意味する。
    """
    result = subprocess.run(
        ["git", "status", "--porcelain", "--"] + files,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    for line in result.stdout.splitlines():
        if not line:
            continue
        index_status = line[0]
        if index_status not in (" ", "?"):
            return True
    return False


def _create_test_update_draft_branch(successful_files: list[str], commit_message: str) -> str:
    """テストの陳腐化(triage_type == "test_update")を検知した際の「優雅な一時停止」
    (Graceful Suspend)。人間の確認を経ずにテストコードの変更を作業中のブランチへ直接
    コミットしないよう、都度新規の隔離ドラフトブランチを作成し、そちらにのみコミットする。

    処理完了後もこのドラフトブランチのまま留まり、元のブランチへは戻さない(意図的な設計)。
    人間が「見慣れないブランチにいる」ことに気づき、レビュー・マージを行うことを促す
    ための安全装置。
    """
    branch_name = (
        f"draft/test-update-{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    print(
        f"\n🌿 [Graceful Suspend] テストの陳腐化を検知したため、隔離ドラフトブランチ "
        f"'{branch_name}' を作成します..."
    )
    result = subprocess.run(
        ["git", "checkout", "-b", branch_name],
        cwd=str(TARGET_APP_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    if result.returncode != 0:
        print(
            f"🚨 致命的エラー: ドラフトブランチ '{branch_name}' の作成に失敗しました:\n{result.stderr}"
        )
        sys.exit(1)

    subprocess.run(
        ["git", "add", "--"] + successful_files,
        cwd=str(TARGET_APP_DIR),
        check=True,
    )
    if not _has_staged_changes(TARGET_APP_DIR, successful_files):
        print("✅ 変更がなかったためドラフトブランチへのコミットをスキップしました")
        return branch_name

    subprocess.run(
        ["git", "commit", "-m", commit_message, "--"] + successful_files,
        cwd=str(TARGET_APP_DIR),
        check=True,
    )
    print(
        "⚠️ テストの陳腐化を検知し、修復ドラフトブランチを作成しました。"
        f"レビュー・マージは人間が行ってください（ブランチ: {branch_name}）"
    )
    return branch_name


AUTO_AUDIT_BRANCH = "auto-audit-temp"


def _ensure_auto_audit_branch() -> None:
    """LangGraph自律修復ループ(Feature 1.x)の実行前に、専用の隔離ブランチへ退避する。

    既存ブランチがあればそのまま切り替え、無ければ作成して切り替える。
    自律編集の影響を作業中の本来のブランチから隔離するための安全装置(Pre-flight)。
    切り替え自体に失敗した場合(未コミット変更との衝突等)は、隔離が担保できない
    ためパイプラインを続行させず安全に停止する。
    """
    print(
        f"\n🌿 [Pre-flight] 自律修復ループ用の隔離ブランチ '{AUTO_AUDIT_BRANCH}' へ退避します..."
    )
    exists = (
        subprocess.run(
            ["git", "rev-parse", "--verify", AUTO_AUDIT_BRANCH],
            cwd=str(TARGET_APP_DIR),
            capture_output=True,
        ).returncode
        == 0
    )

    cmd = (
        ["git", "checkout", AUTO_AUDIT_BRANCH]
        if exists
        else ["git", "checkout", "-b", AUTO_AUDIT_BRANCH]
    )
    result = subprocess.run(
        cmd,
        cwd=str(TARGET_APP_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    if result.returncode != 0:
        print(
            f"🚨 致命的エラー: ブランチ '{AUTO_AUDIT_BRANCH}' への切り替えに失敗しました:\n{result.stderr}"
        )
        sys.exit(1)
    print(f"   ✅ ブランチ '{AUTO_AUDIT_BRANCH}' で作業します ({TARGET_APP_DIR})。")


# --- Test-Driven Escalation Gatekeeper (アーキテクチャ統合 - 追加課題N: 選択的・並列実行) ---
async def verify_logic_with_pytest(target_file: Path) -> tuple[bool, str]:
    """pytest-testmon(変更影響テストの選択)+ pytest-xdist(並列実行)で、決定論的に
    ロジックの正しさを検証する。

    Ollamaが「文法的には正しいが論理が破綻したコード」を出力するFalse Positiveは、
    Ruff/Pyrightのような静的解析では検知できない。実際にテストを走らせて確認する
    絶対的なゲートキーパーとして機能し、失敗時はコミットをブロックしてClaudeパイプラインへの
    エスカレーション判断に使う。

    対象ファイルに対応する単一のテストファイルを推測して単体実行する(旧実装)のではなく、
    テストスイート全体を対象に `--testmon` で前回実行からの変更差分に関係するテストのみへ
    自動的に絞り込み、`-n auto` でCPUコア数に応じて並列実行する。これにより、プロジェクト
    全体のテストを毎回フル実行するO(N)のレイテンシ劣化を避けつつ、決定論的な検証としての
    厳密さは保つ(testmonは実行済みテストのコードカバレッジに基づき、変更されたコードパスに
    依存するテストのみを再実行対象として選択する)。target_fileは呼び出し元でのログ・
    エスカレーション文脈のためにのみ使用し、テスト選択自体はtestmonに委ねる。
    """
    print(
        f"   🧪 [Pytest Gatekeeper] testmon+xdistでテストスイート全体を選択的・並列検証します... "
        f"(トリガー: {target_file.name})"
    )
    try:
        result = subprocess.run(
            ["uv", "run", "pytest", "--testmon", "-n", "auto", "-v"],
            cwd=str(TARGET_APP_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=120,
        )
    except Exception as e:
        return False, f"pytestの実行に失敗しました: {e}"

    if result.returncode == 0:
        return True, "OK"

    tail = (result.stdout + "\n" + result.stderr).strip()
    return False, tail[-4000:]


async def _run_claude_pipeline_and_commit(
    user_instruction: str, log_path: Path, deduped_log: str, commit_message: str
) -> None:
    """Claudeパイプライン(Tool Calling + Pydantic + 自己修正ループ + libcst AST置換)を実行し、
    成功したファイルを一括コミットする。

    main_flowの通常経路(engine=="claude")と、Ollama自律修復がpytest検証に失敗した際の
    エスカレーション経路の両方から共有される。
    """
    static_context_path = build_static_context()

    triage_data = await phase2_claude_translation(user_instruction, log_path)
    tasks = triage_data.get("tasks", [])
    success_count, successful_files = await phase3_aider_execution(
        tasks, deduped_log, static_context_path
    )

    # --- Graceful Suspend: テストの陳腐化(triage_type == "test_update")を1件でも検知した
    # 場合は、現在の作業ブランチへの通常コミット経路を完全にスキップし、人間レビュー専用の
    # 隔離ドラフトブランチへのみコミットして即座に終了する(以降の通常コミット処理へは
    # 一切フォールスルーしない)。
    if any(t.get("triage_type") == "test_update" for t in tasks):
        if success_count > 0 and successful_files:
            _create_test_update_draft_branch(successful_files, commit_message)
        else:
            print(
                "⚠️ テストの陳腐化が検知されましたが、適用に成功したファイルが"
                "なかったためドラフトブランチの作成をスキップしました。"
            )
        return

    if success_count > 0 and successful_files:
        print(
            f"\n📦 {success_count}件の成功ファイルを一括コミット(Bulk Commit)します..."
        )
        try:
            subprocess.run(
                ["git", "add", "--"] + successful_files,
                cwd=str(TARGET_APP_DIR),
                check=True,
            )
            if not _has_staged_changes(TARGET_APP_DIR, successful_files):
                print("✅ 変更がなかったため一括コミットをスキップしました")
            else:
                subprocess.run(
                    ["git", "commit", "-m", commit_message, "--"] + successful_files,
                    cwd=str(TARGET_APP_DIR),
                    check=True,
                )
                print("✅ 一括コミット完了。")
        except Exception as e:
            print(f"⚠️ コミット失敗: {e}")


async def _process_target(user_instruction: str, engine: str, log_path: Path) -> None:
    """エラーログの認知負荷検査からエンジン別のディスパッチ(Claude/Ollama)までを行う。

    main_flowから抽出しているのは、CognitiveLoadExceededErrorを上位(main_flow)の
    try/exceptで一括して捕捉し、Graceful Shutdown(タスクのスキップ)へ落とし込める
    ようにするため(main_flow側で長大なブロックをtry/exceptで再インデントする必要を
    避け、可読性を保つ)。
    """
    with open(log_path, "r", encoding="utf-8") as f:
        raw_error_log = f.read()

    # Cognitive Load Auditor フェイルセーフ: エラーログ自体が肥大化しやすい箇所での早期検査。
    log_ok, log_detail = check_cognitive_load(
        raw_error_log, max_lines=MAX_ERROR_LOG_LINES
    )
    if not log_ok:
        raise CognitiveLoadExceededError(f"エラー範囲が広すぎます ({log_detail})")

    deduped_log = acd_phase1_dedup(raw_error_log)

    if engine == "claude":
        # --- Claudeパイプライン(Tool Calling + Pydantic + 自己修正ループ + libcst AST置換) ---
        await _run_claude_pipeline_and_commit(
            user_instruction,
            log_path,
            deduped_log,
            "fix: Claudeパイプラインによる一括自動修正",
        )

    else:
        # --- LangGraph自律修復ループ (Ollama, Feature 1.x) ---
        # Phase 2(Claude)によるタスク一覧生成を経由しないため、対象ファイルはエラーログ内で
        # 最初に言及されたファイルから暫定的に決定する(複数ファイル対応・選定戦略の見直しは
        # 次の検証ステップで詰める前提の第一実装)。
        findings = acd_parse_error_locations(deduped_log)
        if not findings:
            print(
                "\n✅ エラーログにファイル参照が見つからず、自律修復ループの対象がありません。"
            )
        else:
            resolved_target = _resolve_target_file(findings[0][0])
            if resolved_target is None:
                print(
                    f"⚠️ 警告: 自律修復対象ファイルが解決できません -> {findings[0][0]}"
                )
            else:
                print(
                    f"\n🤖 [LangGraph] 自律修復ループを開始します。対象: {resolved_target}"
                )
                from tools.agent_graph import run_self_repair

                final_state = await asyncio.to_thread(
                    run_self_repair, str(resolved_target)
                )
                revision_count = final_state.get("revision_count", 0)
                print(
                    f"   最終ステータス: {final_state.get('status')} / 修正回数: {revision_count}"
                )

                if revision_count > 0:
                    # --- Test-Driven Escalation Gatekeeper: 静的解析(Ruff/Pyright)では
                    # 検知できない「文法的には正しいが論理が破綻したコード」を、決定論的な
                    # pytest実行で最終的にゲートする。失敗した場合はコミットせず、
                    # Claudeパイプラインへエスカレーションする(Human-in-the-Loopの起点)。
                    test_ok, test_detail = await verify_logic_with_pytest(
                        resolved_target
                    )

                    if test_ok:
                        rel_path = str(resolved_target)
                        print(
                            "\n📦 自律修復ループによる変更を一括コミット(Bulk Commit)します..."
                        )
                        try:
                            subprocess.run(
                                ["git", "add", "--", rel_path],
                                cwd=str(TARGET_APP_DIR),
                                check=True,
                            )
                            if not _has_staged_changes(TARGET_APP_DIR, [rel_path]):
                                print(
                                    "✅ 変更がなかったため一括コミットをスキップしました"
                                )
                            else:
                                subprocess.run(
                                    [
                                        "git",
                                        "commit",
                                        "-m",
                                        "fix: LangGraph自律修復ループによる自動修正",
                                        "--",
                                        rel_path,
                                    ],
                                    cwd=str(TARGET_APP_DIR),
                                    check=True,
                                )
                                print("✅ 一括コミット完了。")

                                # --- 推論軌跡SFTデータ自動抽出フック(フライホイール化) ---
                                print(
                                    "\n🌀 [Flywheel] 今回の修復軌跡を学習データとして抽出します..."
                                )
                                sft_result = subprocess.run(
                                    [
                                        "uv",
                                        "run",
                                        "python",
                                        "tools/extract_agent_sft.py",
                                    ],
                                    cwd=str(BASE_DIR),
                                    capture_output=True,
                                    text=True,
                                    encoding="utf-8",
                                    errors="strict",
                                )
                                if sft_result.stdout:
                                    print(sft_result.stdout, end="")
                                if sft_result.stderr:
                                    print(sft_result.stderr, end="")
                                if sft_result.returncode == 0:
                                    print("✅ 学習データの蓄積が完了しました。")
                                else:
                                    print(
                                        f"⚠️ 学習データの抽出に失敗しました (code={sft_result.returncode})。"
                                    )
                        except Exception as e:
                            print(f"⚠️ コミット失敗: {e}")
                    else:
                        print(
                            "\n🚨 [Escalation] Ollamaの修正が論理テストに失敗しました。"
                            "Claudeパイプラインへエスカレーションします。"
                        )
                        if not os.getenv("ANTHROPIC_API_KEY"):
                            print(
                                "🚨 [Escalation] ANTHROPIC_API_KEY が未設定のため、"
                                "Claudeパイプラインへのエスカレーションを実行できません。"
                            )
                        else:
                            escalation_instruction = (
                                f"{user_instruction}\n\n"
                                "【エスカレーション経緯】ローカルLLM(Ollama)による自律修復ループは完走しましたが、"
                                f"決定論的テスト(pytest)による検証に失敗しました。対象ファイル: {resolved_target}\n"
                                f"【Pytest失敗内容】\n{test_detail}"
                            )
                            await _run_claude_pipeline_and_commit(
                                escalation_instruction,
                                log_path,
                                deduped_log,
                                "fix: Claudeパイプラインへのエスカレーションによる自動修正",
                            )


async def main_flow(user_instruction: str, engine: str = "ollama"):
    print(f"\n🔀 [Engine] 選択されたエンジン: {engine}")

    # V8.7.1: .envの確実な読み込みとフェイルファスト（鍵の生存確認）
    load_dotenv(BASE_DIR / ".env")
    if engine == "claude" and not os.getenv("ANTHROPIC_API_KEY"):
        print("🚨 致命的エラー: ANTHROPIC_API_KEY が .env に設定されていません。")
        sys.exit(1)

    global TARGET_APP_DIR, TARGET_CODE_DIR, TARGET_PYTHON
    TARGET_APP_DIR, TARGET_CODE_DIR, TARGET_PYTHON = _route_target_domain(
        user_instruction
    )

    await startup_local_services()

    await phase0_ruff_autofix()

    # --- Pre-flight: 自律修復ループ用の隔離ブランチへ退避(エンジン非依存) ---
    _ensure_auto_audit_branch()

    # --- 共通前処理: エラーログ抽出 + 認知負荷監視(どちらのエンジンでも必須) ---
    log_path = await phase1_audit(is_final=False)
    if not log_path or not log_path.exists():
        return

    try:
        await _process_target(user_instruction, engine, log_path)
    except CognitiveLoadExceededError as e:
        print(f"\n🚨 Cognitive Overload: {e}。タスクを分割（Split）してください。")
        return

    await phase1_audit(is_final=True)

    print(
        "\n🔄 [Post-flight] 修正を適用した状態で、サービス群のオートヒール(自動復旧)を試みます..."
    )
    await startup_local_services()

    print("\n" + "🌟" * 25)
    print("🎯 【V8.8 (Tool-Augmented) 対話型・自律パイプライン完走 (超・可観測仕様)】")
    print(
        "   すべてのフェーズが終了しました。Gitログと final_error_log.txt を確認してください。"
    )
    print(
        "   ※ 万が一、修正に失敗しエラーが悪化していた場合は、以下のコマンドで一撃ロールバックが可能です:"
    )
    print(f"   git -C {TARGET_APP_DIR} reset --hard HEAD~1")
    print("🌟" * 25 + "\n")

    # --- V8.9: Graceful Shutdown ---
    # フロントエンド等のfire-and-forgetバックグラウンドタスクが、main_flow終了時点で
    # まだ起動待機ポーリング中の場合、asyncio.run()のクリーンアップにより無記録で
    # 強制キャンセルされてしまう(Issue 1調査で判明)。ここで明示的にキャンセル+待機し、
    # _on_frontend_task_done 経由でロガーに記録させてから関数を終える。
    # _bg_tasks はコールバック側(discard)からも変更されるため、反復前に必ずコピーする
    # (「Set changed size during iteration」を防ぐ)。
    tasks_to_cancel = list(_bg_tasks)
    for t in tasks_to_cancel:
        t.cancel()
    if tasks_to_cancel:
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    # dmypyデーモンの停止(Issue 2: ゾンビプロセス化防止)。
    # NOTE: `dmypy stop` は位置引数を一切受け付けない(`--help`で確認済み)。
    # TARGET_CODE_DIR を渡すと "unrecognized arguments" でdmypy自体がエラー終了し、
    # デーモンが停止されないままゾンビ化する。そのため引数なしで呼び出す。
    subprocess.run(
        [str(TARGET_PYTHON), "-m", "mypy.dmypy", "stop"],
        cwd=str(TARGET_APP_DIR),
        capture_output=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nazo-Agent オーケストレーター")
    parser.add_argument(
        "--prompt", type=str, help="プロンプトファイルのパス (オプション)"
    )
    parser.add_argument(
        "--engine",
        type=str,
        choices=["ollama", "claude"],
        default=os.getenv("NAZO_AGENT_ENGINE", "ollama"),
        help=(
            "修正エンジン。ollama: LangGraph自律修復ループ(既定) / "
            "claude: Tool Calling防弾パイプライン。"
            "環境変数 NAZO_AGENT_ENGINE でも指定可能(この引数を明示した場合はそちらが優先)。"
        ),
    )
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # 引数でプロンプトファイルが渡された場合は1タスクで終了（バッチ運用モード）
    if args.prompt:
        prompt_path = Path(args.prompt)
        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                instruction = f.read().strip()
            print("\n" + "=" * 50)
            print(
                "🤖 【Nazo-Agent V8.8 (常駐デーモン版)】: ファイルから指示を読み込み実行します..."
            )
            asyncio.run(main_flow(instruction, engine=args.engine))
            sys.exit(0)
        else:
            print(f"🚨 指定されたプロンプトファイルが見つかりません: {prompt_path}")
            sys.exit(1)

    # 引数がない場合は常駐（デーモン）モードへ
    print("\n" + "=" * 50)
    print("🤖 【Nazo-Agent V8.8 (常駐デーモン版)】起動完了")
    print("   終了するには 'exit' または 'quit' と入力してEnterを2回押してください。")
    print("=" * 50)

    while True:
        print("\n🤖 修正指示を入力してください (完了: 空行でEnter2回 / 終了: 'exit'):")
        print("-" * 50)
        lines = []
        while True:
            try:
                line = input()
                if line == "":
                    if lines and lines[-1] == "":
                        break
                lines.append(line)
            except (EOFError, KeyboardInterrupt):
                print("\n🛑 Nazo-Agentを終了します。お疲れ様でした！")
                sys.exit(0)

        instruction = "\n".join(lines).strip()

        # 終了コマンド判定 (前後の空行を除去して小文字化)
        if instruction.lower() in ["exit", "quit", "exit()", "quit()"]:
            print("\n🛑 Nazo-Agentを安全に終了します。お疲れ様でした！")
            break

        if not instruction:
            print("⚠️ 指示が空です。再度入力してください。")
            continue

        # タスク実行（エラーが起きてもデーモンは死なない）
        try:
            asyncio.run(main_flow(instruction, engine=args.engine))
        except KeyboardInterrupt:
            print(
                "\n⚠️ 処理がユーザーによって強制中断(Ctrl+C)されましたが、エージェントは待機を継続します。"
            )
        except SystemExit as e:
            if e.code == 0:
                raise  # 正常終了(exit/quitコマンド等)はそのまま終了させる
            print(
                f"\n🚨 [Daemon Guard] 子プロセス・関数の異常終了要求 (code={e.code}) を迎撃しました。"
            )
            print("🚨 プロセスのクラッシュを防ぎ、常駐を継続します。")
        except Exception:
            import traceback

            traceback.print_exc()
            print(
                "\n🚨 実行中に予期せぬエラーが発生しましたが、プロセスは常駐を継続します。"
            )

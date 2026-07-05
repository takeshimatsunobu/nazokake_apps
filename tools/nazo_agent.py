import asyncio
import os
import sys
import json
import argparse
import ast
import re
import subprocess
from pathlib import Path
from dotenv import load_dotenv

# --- SRE絶対防衛線: Norton等のプロキシ干渉をスクリプト起動直後に完全遮断 ---
os.environ["NO_PROXY"] = "api.anthropic.com,github.com"
os.environ["no_proxy"] = "api.anthropic.com,github.com"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from pydantic import BaseModel
import anthropic
import httpx

class TokenCircuitBreaker:
    """セッション(デーモン起動中)全体のClaude APIトークン消費を追跡する安全装置。"""
    MAX_TOKENS = 200_000  # 1セッション(デーモン起動中)の安全上限
    used_tokens = 0

    @classmethod
    def add(cls, tokens: int):
        cls.used_tokens += tokens
        if cls.used_tokens > cls.MAX_TOKENS:
            print(f"\n🚨 [Circuit Breaker] セッションのトークン消費上限({cls.MAX_TOKENS})を超過しました！")
            print("🚨 APIコスト保護のため、エージェントを強制停止します。")
            sys.exit(1)  # ここはデーモンごと安全に殺すための意図的な exit

# --- ターゲット環境の設定 ---
BASE_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
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
    (re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"), "<UUID>"),
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
                    blocks.append((node.lineno, getattr(node, "end_lineno", node.lineno), node.name, segment))
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

def _acd_format_block_section(header: str, start: int, end: int, source: str, messages: list[str]) -> str:
    if len(source) > ACD_MAX_BLOCK_CHARS:
        source = source[:ACD_MAX_BLOCK_CHARS] + "\n... (省略) ..."
    unique_messages = "\n".join(f"- {m}" for m in dict.fromkeys(messages))
    return f"### {header} [L{start}-{end}]\n```python\n{source}\n```\n検出された問題:\n{unique_messages}\n"

def acd_ast_compress(error_log: str, project_root: Path, max_chars: int = ACD_MAX_SAFE_CHARS) -> str:
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
            block_cache[key_path] = acd_extract_function_blocks(full_path) if full_path.exists() else []
        block = acd_find_enclosing_block(block_cache[key_path], line_no)
        if block is None:
            unresolved.append(full_line)
            continue
        group_key = (raw_path, block[0], block[1], block[2])
        entry = grouped.setdefault(group_key, {"source": block[3], "messages": []})
        entry["messages"].append(f"L{line_no}: {full_line}")

    sections = [
        _acd_format_block_section(f"{raw_path} :: {name}()", start, end, data["source"], data["messages"])
        for (raw_path, start, end, name), data in grouped.items()
    ]
    if unresolved:
        sections.append("### その他(関数特定不可)\n" + "\n".join(f"- {m}" for m in dict.fromkeys(unresolved)))

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
        _acd_format_block_section(f"{name}()", start, end, data["source"], data["messages"])
        for (start, end, name), data in grouped.items()
    ]
    if unresolved:
        sections.append("### その他(関数特定不可)\n" + "\n".join(f"- {m}" for m in dict.fromkeys(unresolved)))
    return "\n".join(sections)

def build_static_context() -> Path:
    print("\n🔍 [Pre-processing] 対象領域のASTスキャンによる独自要約マップを生成します...")
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
) -> None:
    """汎用: 生存確認 → 停止していればバックグラウンド起動 → ポーリング → 失敗時警告

    子プロセスの標準出力/エラーはlog_pathに保存する(過去にDEVNULLへ捨てていたため、
    UnicodeEncodeError等の実クラッシュ原因が一切見えず診断に手動再現が必要だった)。
    """
    print(f"   -> {emoji} {name} の生存確認中...")
    if await check_http_alive(health_url):
        print(f"   ✅ {already_ok_msg}")
        return
    print(f"   ⚠️ {name} が停止しています。バックグラウンドで自動起動します...")
    try:
        creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) | getattr(subprocess, 'DETACHED_PROCESS', 8)
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
        for i in range(retries):
            await asyncio.sleep(interval)
            print(f"   ⏳ 起動を待機しています... ({i+1}/{retries})")
            if await check_http_alive(health_url):
                print(f"   ✅ {name} の自動起動に成功しました！")
                break
        else:
            print(f"   🚨 警告: {name} の起動が確認できませんでした。手動で起動してください。(ログ: {log_path})")
    except Exception as e:
        print(f"   🚨 {name} 自動起動エラー: {e}")

def _route_target_domain(instruction: str) -> tuple[Path, str, Path]:
    """ユーザーの指示からターゲット領域(ドメイン)と、そのvenv Pythonを自動判定する"""
    instruction_lower = instruction.lower()

    # 領域C (バッチ工場) のキーワード
    batch_keywords = ["バッチ", "工場", "batch", "factory", "パイプライン", "unsloth"]
    if any(kw in instruction_lower for kw in batch_keywords):
        print("🧭 [Router] ターゲット領域を『バッチ工場 (apps/batch_factory)』に設定しました。")
        target_dir = BASE_DIR / "apps" / "batch_factory"
        return (target_dir, "batch", target_dir / ".venv_train" / "Scripts" / "python.exe")

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
        name="Ollama", emoji="🦙", health_url="http://127.0.0.1:11434/api/tags",
        start_cmd=["ollama", "serve"], start_cwd=BASE_DIR,
        already_ok_msg="Ollama は既に稼働しています (Port 11434 OK)。",
        log_path=log_dir / "service_ollama.log", extra_env=utf8_env,
    )

    # 注: .venv_ai/Scripts/fastapi.exe はvenvリロケートの影響で機能不全のため使わず、
    # 常に python.exe -m fastapi 経由で起動する。
    # オートヒール対応: dev モードにより、Aiderのコード修正を即座にホットリロードさせる
    backend_cmd = [str(EVALUATOR_PYTHON), "-m", "fastapi", "dev", "backend/main.py", "--port", "7800"]
    await _ensure_service_alive(
        name="Backend (FastAPI)", emoji="⚙️", health_url="http://127.0.0.1:7800/api/health",
        start_cmd=backend_cmd, start_cwd=EVALUATOR_APP_DIR,
        already_ok_msg="Backend は既に稼働しています (Port 7800 OK)。",
        log_path=log_dir / "service_backend.log", extra_env=utf8_env,
    )

    frontend_cmd = [str(EVALUATOR_PYTHON), "dev_server.py", "7300"]
    frontend_cwd = EVALUATOR_APP_DIR / "frontend" / "public"
    await _ensure_service_alive(
        name="Frontend (dev_server)", emoji="🖥️", health_url="http://127.0.0.1:7300/",
        start_cmd=frontend_cmd, start_cwd=frontend_cwd,
        already_ok_msg="Frontend は既に稼働しています (Port 7300 OK)。",
        log_path=log_dir / "service_frontend.log", extra_env=utf8_env,
    )

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

# --- Phase 1 & 4 ---
async def run_linter(tool_name: str) -> str:
    args = [TARGET_CODE_DIR]
    if tool_name == "radon":
        args = ["cc", TARGET_CODE_DIR, "-n", "C", "-a"] 
    elif tool_name == "bandit":
        args = ["-r", TARGET_CODE_DIR]
    elif tool_name == "ruff":
        args = ["check", TARGET_CODE_DIR]
    cmd = [str(TARGET_PYTHON), "-m", tool_name] + args
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(TARGET_APP_DIR), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60.0)
        except asyncio.TimeoutError:
            process.kill()
            return f"### ツール: {tool_name.upper()} (🚨 タイムアウト)\n```text\nプロセスがハングアップしました。\n```\n"
        output = (stdout.decode('utf-8', errors='replace') + "\n" + stderr.decode('utf-8', errors='replace')).strip()
        if not output:
            output = "出力なし"
        status = "✅ Success" if process.returncode == 0 else f"⚠️ Exited with code {process.returncode}"
        return f"### ツール: {tool_name.upper()} ({status})\n```text\n{output}\n```\n"
    except Exception as e:
        return f"### ツール: {tool_name.upper()} (🚨 実行エラー)\n```text\n{str(e)}\n```\n"

async def phase1_audit(is_final=False) -> Path:
    phase_name = "Phase 4 最終再監査" if is_final else "Phase 1 現状監査"
    print(f"\n🔍 [{phase_name}] ターゲット環境 ({TARGET_APP_DIR.name}/{TARGET_CODE_DIR}) の静的解析を開始します...")
    if not TARGET_PYTHON.exists():
        print(f"🚨 致命的エラー: Python環境が見つかりません: {TARGET_PYTHON}")
        sys.exit(1)
    tools = ["ruff", "mypy", "bandit", "radon"]
    report_lines = [f"# 🔍 統合静的解析ファクトレポート", f"ターゲット: {TARGET_APP_DIR.name}/{TARGET_CODE_DIR}", "---", ""]
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
async def phase2_claude_translation(user_instruction: str, error_log_path: Path) -> dict:
    print("\n🔍 [Phase 2] Claude API による「Aiderタスク」への翻訳・分割を開始します...")
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    with open(error_log_path, "r", encoding="utf-8") as f:
        raw_error_log = f.read()

    deduped_log = acd_phase1_dedup(raw_error_log)
    try:
        compact_context = acd_ast_compress(deduped_log, TARGET_APP_DIR, max_chars=ACD_MAX_SAFE_CHARS)
    except Exception as e:
        print(f"   ⚠️ [ACD Engine] AST抽出に失敗、フェイルセーフで先頭{ACD_MAX_SAFE_CHARS}文字に切り捨てます: {e}")
        compact_context = deduped_log[:ACD_MAX_SAFE_CHARS]
    print(f"   [ACD Engine] AST圧縮完了: {len(raw_error_log)}文字 -> {len(compact_context)}文字")

    # TLS問題を防ぐ防弾設定
    http_client = httpx.AsyncClient(verify=False, trust_env=True, timeout=httpx.Timeout(600.0, connect=30.0))
    client = anthropic.AsyncAnthropic(api_key=api_key, http_client=http_client, max_retries=0)
    
    system_prompt = "あなたは冷徹な設計翻訳機です。JSONデータのみを純粋に出力せよ。"
    system_blocks = [
        {
            "type": "text",
            "text": f"{system_prompt}\n\nあなたはシニアソフトウェアアーキテクトです。以下の「要件定義書」と後ほど提示する「エラーログ」からAiderの修正手順を生成せよ。\n【要件定義書】\n{user_instruction}\n\n【条件】\n厳格な出力スキーマに従い、JSONのみ出力すること(Markdown不要)。",
            "cache_control": {"type": "ephemeral"}
        }
    ]

    result_json = {}
    stop_event = asyncio.Event()

    # 進行状況の表示タスク開始 (ドット印字版)
    progress_task = asyncio.create_task(_progress_dots("Claude API 思考・翻訳中", stop_event))

    try:
        response = await client.messages.create(
            model="claude-sonnet-5",
            max_tokens=8192,
            system=system_blocks,
            messages=[{
                "role": "user",
                "content": f"【エラーログ】\n{compact_context}"
            }]
        )
        stop_event.set()
        await progress_task
        
        text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        report = "\n".join(text_blocks).strip()

        if report.startswith("```json"):
            report = report[7:]
        if report.endswith("```"):
            report = report[:-3]
        report = report.strip()
        result_json = json.loads(report)
        
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
    print("\n" + "="*50)
    print("📋 【Claude 設計翻訳結果（Aiderへの確定指令）】")
    print(f" ［修正対象タスク数］: {len(tasks)} 件")
    for idx, task in enumerate(tasks, 1):
        print(f"   {idx}. {task.get('file_path', '不明なパス')}")
        print(f"      指示: {task.get('instruction', '記述なし')}")
    print("\n ［実装サマリー］:\n  " + result_json.get('summary', '記述なし'))
    print("="*50 + "\n")
    print(f"✅ フェーズ2完了: Aiderへの確定指令書を保存しました -> {triage_path}")
    return result_json

# --- Phase 2 (Tool-Augmented) ---
async def phase2_claude_tool_augmented(user_instruction: str, error_log_path: Path) -> dict:
    """Tool-Augmented版Phase 2。

    tools.ast_mapper.get_symbol_definition / tools.file_reader.read_file_section を
    Claudeに公開し、Claude自身が「双方向推論ループ」で自律的にコードを調査してから
    AiderTask のリストを確定させる。最終提出は submit_aider_plan ツールへの
    tool_choice強制で構造化出力を保証する。
    """
    from tools.ast_mapper import get_symbol_definition
    from tools.file_reader import read_file_section

    print("\n🔍 [Phase 2 / Tool-Augmented] Claude API による自律調査・翻訳を開始します...")
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    with open(error_log_path, "r", encoding="utf-8") as f:
        raw_error_log = f.read()

    deduped_log = acd_phase1_dedup(raw_error_log)
    try:
        compact_context = acd_ast_compress(deduped_log, TARGET_APP_DIR, max_chars=ACD_MAX_SAFE_CHARS)
    except Exception as e:
        print(f"   ⚠️ [ACD Engine] AST抽出に失敗、フェイルセーフで先頭{ACD_MAX_SAFE_CHARS}文字に切り捨てます: {e}")
        compact_context = deduped_log[:ACD_MAX_SAFE_CHARS]

    # TLS問題を防ぐ防弾設定
    http_client = httpx.AsyncClient(verify=False, trust_env=True, timeout=httpx.Timeout(600.0, connect=30.0))
    client = anthropic.AsyncAnthropic(api_key=api_key, http_client=http_client, max_retries=0)

    system_prompt = (
        "あなたは冷徹な設計翻訳機であり、シニアソフトウェアアーキテクトです。"
        "以下の「要件定義書」と後ほど提示する「エラーログ」からAiderの修正手順を生成せよ。\n"
        f"【要件定義書】\n{user_instruction}\n\n"
        "判断に必要な場合は get_symbol_definition / read_file_section ツールで"
        f"対象領域({TARGET_APP_DIR / TARGET_CODE_DIR})の実コードを実際に確認してから判断すること。"
        "調査が完了したら必ず submit_aider_plan ツールで最終結果を提出すること。"
    )

    # Claude API に渡すツール定義(JSON Schema形式)
    investigation_tools = [
        {
            "name": "get_symbol_definition",
            "description": "シンボル名(関数名またはクラス名の完全一致)から、その定義元のソースコード全文をASTで検索して返す。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol_name": {"type": "string", "description": "検索する関数名またはクラス名(完全一致)"},
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
                    "file_path": {"type": "string", "description": "読み込むファイルのパス"},
                    "start_line": {"type": "integer", "description": "開始行(1始まり)"},
                    "end_line": {"type": "integer", "description": "終了行(1始まり・両端含む)"},
                },
                "required": ["file_path", "start_line", "end_line"],
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
                            "file_path": {"type": "string"},
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
    messages = [{"role": "user", "content": f"【エラーログ】\n{compact_context}"}]

    result_json: dict = {}
    stop_event = asyncio.Event()
    progress_task = asyncio.create_task(_progress_dots("Claude API 自律調査・翻訳中", stop_event))

    MAX_TURNS = 5
    try:
        for turn in range(1, MAX_TURNS + 1):
            force_final = (turn == MAX_TURNS)
            response = await client.messages.create(
                model="claude-sonnet-5",
                max_tokens=8192,
                system=system_prompt,
                messages=messages,
                tools=all_tools,
                tool_choice={"type": "tool", "name": "submit_aider_plan"} if force_final else {"type": "auto"},
            )

            # レスポンスから入力・出力トークンを取得して記録
            usage = getattr(response, "usage", None)
            if usage:
                total_tokens = getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0)
                TokenCircuitBreaker.add(total_tokens)

            submit_block = next(
                (b for b in response.content if getattr(b, "type", "") == "tool_use" and b.name == "submit_aider_plan"),
                None,
            )
            if submit_block is not None:
                raw_tasks = submit_block.input.get("tasks", [])
                validated_tasks = [AiderTask(**t).model_dump() for t in raw_tasks]
                result_json = {"tasks": validated_tasks, "summary": submit_block.input.get("summary", "")}
                break

            if response.stop_reason != "tool_use":
                # ツール未使用のまま終了した場合は、次ターンで最終提出を促す
                messages.append({"role": "assistant", "content": response.content})
                messages.append({
                    "role": "user",
                    "content": "調査内容をもとに、必ず submit_aider_plan ツールで最終結果を提出してください。",
                })
                continue

            # 調査ツール呼び出しをPython側で実行し、tool_resultとして履歴に積んで再送する
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if getattr(block, "type", "") != "tool_use":
                    continue
                if block.name == "get_symbol_definition":
                    tool_output = get_symbol_definition(
                        [TARGET_APP_DIR / TARGET_CODE_DIR], block.input.get("symbol_name", "")
                    )
                elif block.name == "read_file_section":
                    tool_output = read_file_section(
                        block.input.get("file_path", ""),
                        block.input.get("start_line", 1),
                        block.input.get("end_line", 1),
                    )
                else:
                    tool_output = f"Error: 未知のツール '{block.name}' です。"
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": tool_output})
            messages.append({"role": "user", "content": tool_results})

        stop_event.set()
        await progress_task

        if not result_json:
            print("\n🚨 Phase 2(Tool-Augmented) 抽出エラー: 最大ターン数内に最終結果が得られませんでした。")
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
    print("\n" + "="*50)
    print("📋 【Claude(Tool-Augmented) 設計翻訳結果（Aiderへの確定指令）】")
    print(f" ［修正対象タスク数］: {len(tasks)} 件")
    for idx, task in enumerate(tasks, 1):
        print(f"   {idx}. {task.get('file_path', '不明なパス')}")
        print(f"      指示: {task.get('instruction', '記述なし')}")
    print("\n ［実装サマリー］:\n  " + result_json.get('summary', '記述なし'))
    print("="*50 + "\n")
    print(f"✅ フェーズ2(Tool-Augmented)完了: Aiderへの確定指令書を保存しました -> {triage_path}")
    return result_json

# --- Phase 3 ---
IDLE_TIMEOUT_SECONDS = 300.0

async def _drain_stream(stream: asyncio.StreamReader, buffer: list, activity: dict) -> None:
    loop = asyncio.get_running_loop()
    while True:
        line = await stream.readline()
        if not line:
            break
        buffer.append(line)
        activity["last"] = loop.time()

async def run_subprocess_with_idle_timeout(process: asyncio.subprocess.Process, idle_timeout: float):
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

async def phase3_aider_execution(tasks: list[dict], deduped_error_log: str, static_context_path: Path) -> tuple[int, list[str]]:
    print(f"\n🔍 [Phase 3] Aider による個別ファイル修正を開始します (対象: {len(tasks)} 件)...")
    if not tasks:
        print("✅ フェーズ3完了: 修正対象タスクが0件のためスキップしました。")
        return 0, []

    clean_env = os.environ.copy()
    clean_env["ANTHROPIC_API_KEY"] = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    clean_env["GEMINI_API_KEY"] = (os.getenv("GEMINI_API_KEY") or "").strip()
    clean_env["PYTHONIOENCODING"] = "utf-8"
    clean_env["PYTHONUTF8"] = "1"

    success_count = 0
    failure_count = 0
    successful_files = []

    for idx, task in enumerate(tasks, 1):
        file_path = task.get("file_path", "")
        instruction = task.get("instruction", "")
        if not file_path or not instruction:
            continue

        target_file = TARGET_APP_DIR / file_path
        print("\n" + "="*50)
        print(f"🛠️  [{idx}/{len(tasks)}] Aider起動: {file_path}")
        print(f"   指示: {instruction}")

        if not target_file.exists():
            print(f"⚠️ 警告: 対象ファイルが存在しません。スキップします -> {target_file}")
            failure_count += 1
            print("⚠️ 部分的障害: このファイルの修正をスキップし、後続のタスクを継続します (縮退運転)。")
            continue

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
            "--model", "anthropic/claude-sonnet-5",
            "--thinking-tokens", "0",
            "--message", full_message,
            "--map-tokens", "0",
            "--no-auto-commits",
            "--cache-prompts",
            "--cache-keepalive-pings", "2",
            "--read", str(static_context_path),
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

            stdout, stderr = await run_subprocess_with_idle_timeout(process, idle_timeout=IDLE_TIMEOUT_SECONDS)
            output = (stdout.decode("utf-8", errors="replace") + "\n" + stderr.decode("utf-8", errors="replace")).strip()
            
            elapsed = asyncio.get_running_loop().time() - start_time
            print(f"⏱️ 処理時間: {elapsed:.1f}秒 ({file_path})")

            if process.returncode == 0:
                print(f"✅ 完了: {file_path}")
                success_count += 1
                successful_files.append(file_path)
            else:
                print(f"⚠️ Aiderが異常終了しました (code={process.returncode}): {file_path}")
                if output:
                    print(f"```text\n{output}\n```\n")
                failure_count += 1
                print("⚠️ 部分的障害: このファイルの修正をスキップし、後続のタスクを継続します (縮退運転)。")
                continue
        except asyncio.TimeoutError:
            process.kill()
            elapsed = asyncio.get_running_loop().time() - start_time
            print(f"⏱️ 処理時間: {elapsed:.1f}秒 ({file_path})")
            print(f"🚨 アイドル・タイムアウト: {file_path} の修正で{int(IDLE_TIMEOUT_SECONDS)}秒間出力が完全に途絶えたため強制終了しました。")
            failure_count += 1
            print("⚠️ 部分的障害: このファイルの修正をスキップし、後続のタスクを継続します (縮退運転)。")
            continue
        except Exception as e:
            if process is not None and process.returncode is None:
                process.kill()
            elapsed = asyncio.get_running_loop().time() - start_time if start_time else 0
            print(f"⏱️ 処理時間: {elapsed:.1f}秒 ({file_path})")
            print(f"🚨 実行エラー ({file_path}): {type(e).__name__} - {str(e)}")
            failure_count += 1
            print("⚠️ 部分的障害: このファイルの修正をスキップし、後続のタスクを継続します (縮退運転)。")
            continue

    print(f"\n🎉 フェーズ3完了: 成功 {success_count} 件 / 失敗 {failure_count} 件 (全 {len(tasks)} 件)")
    return success_count, successful_files

async def main_flow(user_instruction: str):
    # V8.7.1: .envの確実な読み込みとフェイルファスト（鍵の生存確認）
    load_dotenv(BASE_DIR / ".env")
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("🚨 致命的エラー: ANTHROPIC_API_KEY が .env に設定されていません。")
        sys.exit(1)

    global TARGET_APP_DIR, TARGET_CODE_DIR, TARGET_PYTHON
    TARGET_APP_DIR, TARGET_CODE_DIR, TARGET_PYTHON = _route_target_domain(user_instruction)

    await startup_local_services()

    log_path = await phase1_audit(is_final=False)
    if not log_path or not log_path.exists():
        return

    static_context_path = build_static_context()

    # フィーチャートグル: 環境変数でTool-Augmented版を使うか判定 (デフォルトはTrue)
    use_tool_augmented = os.getenv("USE_TOOL_AUGMENTED_PHASE2", "true").lower() == "true"

    if use_tool_augmented:
        print("\n🚀 [Feature Toggle] Tool-Augmented 版の Phase 2 を実行します。")
        triage_data = await phase2_claude_tool_augmented(user_instruction, log_path)
    else:
        print("\n⏪ [Feature Toggle] 従来版の Phase 2 を実行します。")
        triage_data = await phase2_claude_translation(user_instruction, log_path)
    tasks = triage_data.get("tasks", [])
    
    with open(log_path, "r", encoding="utf-8") as f:
        raw_error_log = f.read()
    deduped_log = acd_phase1_dedup(raw_error_log)

    success_count, successful_files = await phase3_aider_execution(tasks, deduped_log, static_context_path)

    if success_count > 0 and successful_files:
        print(f"\n📦 {success_count}件の成功ファイルを一括コミット(Bulk Commit)します...")
        try:
            subprocess.run(["git", "add", "--"] + successful_files, cwd=str(TARGET_APP_DIR), check=True)
            subprocess.run(
                ["git", "commit", "-m", "fix: Aiderによる一括自動修正", "--"] + successful_files,
                cwd=str(TARGET_APP_DIR), check=True,
            )
            print("✅ 一括コミット完了。")
        except Exception as e:
            print(f"⚠️ コミット失敗: {e}")

    await phase1_audit(is_final=True)

    print("\n🔄 [Post-flight] 修正を適用した状態で、サービス群のオートヒール(自動復旧)を試みます...")
    await startup_local_services()

    print("\n" + "🌟"*25)
    print("🎯 【V8.8 (Tool-Augmented) 対話型・自律パイプライン完走 (超・可観測仕様)】")
    print(f"   すべてのフェーズが終了しました。Gitログと final_error_log.txt を確認してください。")
    print(f"   ※ 万が一、修正に失敗しエラーが悪化していた場合は、以下のコマンドで一撃ロールバックが可能です:")
    print(f"   git -C {TARGET_APP_DIR} reset --hard HEAD~1")
    print("🌟"*25 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nazo-Agent オーケストレーター")
    parser.add_argument("--prompt", type=str, help="プロンプトファイルのパス (オプション)")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # 引数でプロンプトファイルが渡された場合は1タスクで終了（バッチ運用モード）
    if args.prompt:
        prompt_path = Path(args.prompt)
        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                instruction = f.read().strip()
            print("\n" + "="*50)
            print("🤖 【Nazo-Agent V8.8 (常駐デーモン版)】: ファイルから指示を読み込み実行します...")
            asyncio.run(main_flow(instruction))
            sys.exit(0)
        else:
            print(f"🚨 指定されたプロンプトファイルが見つかりません: {prompt_path}")
            sys.exit(1)

    # 引数がない場合は常駐（デーモン）モードへ
    print("\n" + "="*50)
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
            asyncio.run(main_flow(instruction))
        except KeyboardInterrupt:
            print("\n⚠️ 処理がユーザーによって強制中断(Ctrl+C)されましたが、エージェントは待機を継続します。")
        except SystemExit as e:
            if e.code == 0:
                raise  # 正常終了(exit/quitコマンド等)はそのまま終了させる
            print(f"\n🚨 [Daemon Guard] 子プロセス・関数の異常終了要求 (code={e.code}) を迎撃しました。")
            print("🚨 プロセスのクラッシュを防ぎ、常駐を継続します。")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"\n🚨 実行中に予期せぬエラーが発生しましたが、プロセスは常駐を継続します。")
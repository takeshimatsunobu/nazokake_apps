import asyncio
import os
import sys
import json
import argparse
import ast
import re
from pathlib import Path
from dotenv import load_dotenv

# Windowsのデフォルトコンソール(cp932)での UnicodeEncodeError クラッシュを防ぐ
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from pydantic import BaseModel
import anthropic
import httpx

# --- ターゲット環境の設定（ファクトに基づく） ---
BASE_DIR = Path(__file__).resolve().parent
TARGET_APP_DIR = BASE_DIR / "nazokake-evaluator"
TARGET_PYTHON = TARGET_APP_DIR / ".venv_ai" / "Scripts" / "python.exe"
TARGET_CODE_DIR = "backend"

# --- Structured Output Schema ---
class AiderTask(BaseModel):
    file_path: str
    instruction: str

class TriageResult(BaseModel):
    tasks: list[AiderTask]
    summary: str

_ACD_NOISE_PATTERNS = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"), "<TIME>"),
    (re.compile(r"0x[0-9a-fA-F]{4,}"), "<HEX>"),
    (re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"), "<UUID>"),
    (re.compile(r"\b(?:pid|PID)[=:\s]?\d+\b"), "<PID>"),
]

def acd_mask_noise(line: str) -> str:
    """動的ノイズ(タイムスタンプ/16進アドレス/UUID/PID)を固定トークンへ置換する。
    これにより、値だけが変動する同種のエラー行を重複として検知できるようにする。"""
    masked = line
    for pattern, replacement in _ACD_NOISE_PATTERNS:
        masked = pattern.sub(replacement, masked)
    return masked

def acd_phase1_dedup(error_log: str) -> str:
    """ACDエンジン Phase1: 動的ノイズをマスクした上で、連続する重複エラー行を折りたたむ"""
    lines = error_log.split("\n")
    masked_lines = [acd_mask_noise(line) for line in lines]
    result, i = [], 0
    while i < len(lines):
        j = i + 1
        while j < len(lines) and masked_lines[j] == masked_lines[i]:
            j += 1
        result.append(lines[i])
        if j - i > 1:
            result.append(f"[Previous error repeated {j - i - 1} times]")
        i = j
    return "\n".join(result)

def acd_extract_symbols(file_path: Path) -> list[str]:
    """ACDエンジン Phase2: AST解析でclass/def名を抽出"""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return []
    return [n.name for n in ast.walk(tree) if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]

def acd_slice_context(deduped_log: str, file_path: str, symbols: list[str], window: int = 20) -> str:
    """ACDエンジン Phase3: ファイル名/シンボル名ヒット行の前後window行を抽出・結合"""
    lines = deduped_log.split("\n")
    keywords = [file_path] + symbols
    hits = [(max(0, i - window), min(len(lines), i + window + 1))
            for i, line in enumerate(lines) if any(kw and kw in line for kw in keywords)]
    if not hits:
        return ""
    hits.sort()
    merged = [hits[0]]
    for s, e in hits[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return "\n".join("...\n" + "\n".join(lines[s:e]) + "\n..." for s, e in merged)

def build_repo_summary_map(target_dir: Path) -> str:
    """独自要約マップ: 対象領域のclass/def名一覧を静的テキストとして1回だけ生成"""
    lines = ["# リポジトリ構造要約マップ"]
    for py_file in sorted(target_dir.rglob("*.py")):
        symbols = acd_extract_symbols(py_file)
        if symbols:
            lines.append(f"- {py_file.relative_to(target_dir)}: {', '.join(symbols)}")
    return "\n".join(lines)

IDLE_TIMEOUT_SECONDS = 300.0
ACD_SLICE_WINDOW = 10  # 速度優先: 前後20行→10行に縮小してプロンプトを圧縮

async def _drain_stream(stream: asyncio.StreamReader, buffer: list, activity: dict) -> None:
    """ストリームを1行ずつ読み込み、読み込むたびに最終活動時刻を更新する"""
    loop = asyncio.get_running_loop()
    while True:
        line = await stream.readline()
        if not line:
            break
        buffer.append(line)
        activity["last"] = loop.time()

async def run_subprocess_with_idle_timeout(
    process: asyncio.subprocess.Process, idle_timeout: float = IDLE_TIMEOUT_SECONDS
) -> tuple[bytes, bytes]:
    """静的な総時間タイムアウトではなく、標準出力/標準エラー出力が完全に途絶えた
    アイドル時間でハングアップを検知する。出力が続いている限り処理を継続させる。"""
    loop = asyncio.get_running_loop()
    activity = {"last": loop.time()}
    stdout_buf: list = []
    stderr_buf: list = []

    stdout_task = asyncio.ensure_future(_drain_stream(process.stdout, stdout_buf, activity))
    stderr_task = asyncio.ensure_future(_drain_stream(process.stderr, stderr_buf, activity))
    wait_task = asyncio.ensure_future(process.wait())

    try:
        while True:
            done, _ = await asyncio.wait(
                {stdout_task, stderr_task, wait_task},
                timeout=idle_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if wait_task in done:
                await asyncio.gather(stdout_task, stderr_task)
                break
            if loop.time() - activity["last"] >= idle_timeout:
                raise asyncio.TimeoutError(
                    f"{idle_timeout}秒間、標準出力・標準エラー出力に完全な沈黙が続きました。"
                )
    finally:
        for task in (stdout_task, stderr_task, wait_task):
            if not task.done():
                task.cancel()

    return b"".join(stdout_buf), b"".join(stderr_buf)

async def run_linter(tool_name: str) -> str:
    """単一のLintツールを非同期サブプロセスで実行し、生ログを抽出する"""
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
            *cmd,
            cwd=str(TARGET_APP_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60.0)
        except asyncio.TimeoutError:
            process.kill()
            return f"### ツール: {tool_name.upper()} (🚨 タイムアウト: 60秒超過)\n```text\nプロセスがハングアップしました。\n```\n"
            
        output = (stdout.decode('utf-8', errors='replace') + "\n" + stderr.decode('utf-8', errors='replace')).strip()
        if not output:
            output = "出力なし（正常または検出事項なし）"
            
        status = "✅ Success" if process.returncode == 0 else f"⚠️ Exited with code {process.returncode}"
        return f"### ツール: {tool_name.upper()} ({status})\n```text\n{output}\n```\n"
        
    except Exception as e:
        return f"### ツール: {tool_name.upper()} (🚨 実行エラー)\n```text\n{str(e)}\n```\n"

async def my_import_check():
    """仮想環境の生存確認"""
    if not TARGET_PYTHON.exists():
        print(f"🚨 致命的エラー: ターゲットのPython環境が見つかりません: {TARGET_PYTHON}")
        sys.exit(1)

async def phase1_audit(is_final=False) -> Path:
    """フェーズ1 & 4: ツールの完全非同期実行"""
    phase_name = "Phase 4 最終再監査" if is_final else "Phase 1 現状監査"
    print(f"\n🔍 [{phase_name}] ターゲット環境 ({TARGET_APP_DIR.name}/{TARGET_CODE_DIR}) の静的解析を開始します...")
    await my_import_check()

    tools = ["ruff", "mypy", "bandit", "radon"]
    report_lines = [f"# 🔍 統合静的解析ファクトレポート", f"ターゲット: {TARGET_APP_DIR.name}/{TARGET_CODE_DIR}", "---", ""]
    
    tasks = [run_linter(tool) for tool in tools]
    results = await asyncio.gather(*tasks)
    
    for tool, result in zip(tools, results):
        print(f"✅ {tool.upper()} の解析が完了しました。")
        report_lines.append(result)

    audit_dir = BASE_DIR / "audit_reports"
    audit_dir.mkdir(exist_ok=True)
    out_name = "final_error_log.txt" if is_final else "error_log.txt"
    out_file = audit_dir / out_name
    
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
        
    print(f"🎉 {phase_name}完了: ファクトレポートを生成しました -> {out_file}")
    return out_file

async def phase2_claude_translation(user_instruction: str, deduped_error_log: str, repo_summary_map: str) -> dict:
    """フェーズ2: Claudeによる要件定義書の「Aiderタスク」への翻訳と分割"""
    print("\n🔍 [Phase 2] Claude API による「Aiderタスク」への翻訳・分割を開始します...")

    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()

    # Nortonインスペクション突破の防弾仕様
    http_client = httpx.AsyncClient(
        verify=False,
        trust_env=True,
        timeout=httpx.Timeout(600.0, connect=30.0)
    )
    client = anthropic.AsyncAnthropic(api_key=api_key, http_client=http_client, max_retries=0)

    # Prompt Caching: 不変層(Static)と可変層(Dynamic)を物理分離する。
    # Static層(要件定義書+要約マップ)の末尾にcache_controlを付与し、
    # 同一セッション内の再呼び出し時のトークンコストを削減する。
    static_block = f"""
あなたはシニアソフトウェアアーキテクトです。
以下の「ユーザーの要件定義書」と「リポジトリ構造要約マップ」を踏まえ、
Aider（自律コーディングエージェント）に渡すための「ファイルごとの超具体的な修正手順」に翻訳・分割してください。

【ユーザーの要件定義書】
{user_instruction}

【リポジトリ構造要約マップ】
{repo_summary_map}

【厳格な抽出と翻訳の条件】
1. Aiderが迷わないよう、対象ファイルのどのクラス/関数をどのように修正するか、極めて具体的に `instruction` に記載すること。
2. 以下のJSONスキーマに完全に従うJSONフォーマットのみを出力すること。Markdownのコードブロック(```json)は不要です。

{{
  "tasks": [
    {{
      "file_path": "backend/...",
      "instruction": "関数○○をtry-exceptで囲み..."
    }}
  ],
  "summary": "全体の実装方針とアーキテクチャの要約"
}}
"""
    dynamic_block = f"【現在の静的解析エラーログ（ACD圧縮済み）】\n{deduped_error_log}"

    max_retries = 3
    result_json = {}

    for attempt in range(max_retries):
        try:
            response = await client.messages.create(
                model="claude-sonnet-5",
                max_tokens=8192,
                system="あなたは冷徹な設計翻訳機です。JSONデータのみを純粋に出力せよ。",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": static_block, "cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": dynamic_block},
                    ],
                }],
                extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
            )
            
            text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
            report = "\n".join(text_blocks).strip()
            
            # JSONブロックのサニタイズ
            if report.startswith("```json"):
                report = report[7:]
            if report.startswith("```"):
                report = report[3:]
            if report.endswith("```"):
                report = report[:-3]
                
            result_json = json.loads(report.strip())
            break
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"\n🚨 Phase 2 抽出エラー (リトライ上限到達): {type(e).__name__} - {str(e)}")
                await http_client.aclose()
                sys.exit(1)
            print(f"\n⚠️ Phase 2 APIエラー: {type(e).__name__}. 3秒後にリトライします...")
            await asyncio.sleep(3 * (2 ** attempt))

    await http_client.aclose()

    tasks = result_json.get("tasks", [])
    print("\n" + "="*50)
    print("📋 【Claude 設計翻訳結果（Aiderへの確定指令）】")
    print(f" ［修正対象タスク数］: {len(tasks)} 件")
    for idx, task in enumerate(tasks, 1):
        print(f"   {idx}. {task.get('file_path', '不明なパス')}")
        print(f"      指示: {task.get('instruction', '記述なし')}")
    print("\n ［実装サマリー］:")
    print(f"  {result_json.get('summary', '記述なし')}")
    print("="*50 + "\n")

    triage_path = BASE_DIR / "audit_reports" / "triage_result.json"
    with open(triage_path, "w", encoding="utf-8") as f:
        json.dump(result_json, f, indent=2, ensure_ascii=False)
        
    print(f"✅ フェーズ2完了: Aiderへの確定指令書を保存しました -> {triage_path}")
    return result_json

async def phase3_aider_execution(tasks: list[dict], deduped_error_log: str, static_context_path: Path) -> tuple[int, list[str]]:
    """フェーズ3: Aiderサブプロセスを直列起動し個別撃破 (サーキットブレーカー搭載)"""
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
    successful_files: list[str] = []

    for idx, task in enumerate(tasks, 1):
        file_path = task.get("file_path", "")
        instruction = task.get("instruction", "")
        target_file = TARGET_APP_DIR / file_path

        print(f"\n{'='*50}")
        print(f"🛠️  [{idx}/{len(tasks)}] Aider起動: {file_path}")
        print(f"   指示: {instruction}")
        print(f"{'='*50}")

        if not target_file.exists():
            print(f"⚠️ 警告: 対象ファイルが存在しません -> {target_file}")
            failure_count += 1
            print("🚨 サーキットブレーカー発動: カスケード障害を防ぐため後続処理を安全に遮断しました。")
            break

        # ACDエンジン Phase2/3: 対象ファイルのシンボルを抽出し、圧縮済みエラーログから
        # 関連箇所だけをスライスしてAiderの指示に連結する(--messageへ注入)。
        symbols = acd_extract_symbols(target_file)
        context_snippet = acd_slice_context(deduped_error_log, file_path, symbols, window=ACD_SLICE_WINDOW)
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
            # 送信するデータがないため直ちに閉じる(communicate()の内部挙動と同様)。
            process.stdin.close()

            start_time = asyncio.get_running_loop().time()
            try:
                stdout, stderr = await run_subprocess_with_idle_timeout(process, idle_timeout=IDLE_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                process.kill()
                elapsed = asyncio.get_running_loop().time() - start_time
                print(f"⏱️ 処理時間: {elapsed:.1f}秒 ({file_path})")
                print(f"🚨 アイドル・タイムアウト: {file_path} の修正で{int(IDLE_TIMEOUT_SECONDS)}秒間出力が完全に途絶えたため強制終了しました。")
                failure_count += 1
                print("🚨 サーキットブレーカー発動: カスケード障害を防ぐため後続処理を安全に遮断しました。")
                break

            elapsed = asyncio.get_running_loop().time() - start_time
            print(f"⏱️ 処理時間: {elapsed:.1f}秒 ({file_path})")

            output = (stdout.decode("utf-8", errors="replace") + "\n" + stderr.decode("utf-8", errors="replace")).strip()

            if process.returncode == 0:
                print(f"✅ 完了: {file_path}")
                success_count += 1
                successful_files.append(file_path)
            else:
                print(f"⚠️ Aiderが異常終了しました (code={process.returncode}): {file_path}")
                if output:
                    print(f"```text\n{output}\n```")
                failure_count += 1
                print("🚨 サーキットブレーカー発動: カスケード障害を防ぐため後続処理を安全に遮断しました。")
                break

        except Exception as e:
            if process is not None and process.returncode is None:
                process.kill()
            if start_time is not None:
                elapsed = asyncio.get_running_loop().time() - start_time
                print(f"⏱️ 処理時間: {elapsed:.1f}秒 ({file_path})")
            print(f"🚨 実行エラー ({file_path}): {type(e).__name__} - {str(e)}")
            failure_count += 1
            print("🚨 サーキットブレーカー発動: カスケード障害を防ぐため後続処理を安全に遮断しました。")
            break

    print(f"\n🎉 フェーズ3完了: 成功 {success_count} 件 / 失敗 {failure_count} 件 (全 {len(tasks)} 件)")
    return success_count, successful_files

async def main_flow(user_instruction: str):
    load_dotenv(BASE_DIR / ".env")
    
    if not user_instruction:
        print("🚨 エラー: 指示が入力されていません。")
        return

    # Phase 1: 初期監査
    log_path = await phase1_audit(is_final=False)
    if not log_path or not log_path.exists():
        return

    # ACDエンジン Phase1(重複排除) + 独自要約マップの事前生成(いずれもStatic層用)
    with open(log_path, "r", encoding="utf-8") as f:
        deduped_log = acd_phase1_dedup(f.read())
    repo_summary_map = build_repo_summary_map(TARGET_APP_DIR / TARGET_CODE_DIR)

    # Static(不変層)を一時ファイル化し、Aiderの--readで不変プレフィックスとして
    # 強制する。ループ全体で内容を変更しないことで、Aider側のプロンプトキャッシュ
    # (--cache-prompts)がファイル間で再ヒットする可能性を最大化する。
    static_context_path = BASE_DIR / "audit_reports" / "static_context.md"
    with open(static_context_path, "w", encoding="utf-8") as f:
        f.write(f"# 要件定義書\n{user_instruction}\n\n# リポジトリ構造要約マップ\n{repo_summary_map}")

    # Phase 2: Claudeによるタスク翻訳
    triage_data = await phase2_claude_translation(user_instruction, deduped_log, repo_summary_map)
    tasks = triage_data.get("tasks", [])

    # Phase 3: Aider実行
    success_count, successful_files = await phase3_aider_execution(tasks, deduped_log, static_context_path)

    # Bulk Commit: Aider側の自動コミットは無効化しているため、成功分をここで一括コミットする。
    # `git add -A` は作業ツリー全体を巻き込むため使用禁止とし、成功したファイルのみを
    # 明示的にステージングする(爆発半径の制御)。
    if successful_files:
        print("\n🔍 [Bulk Commit] 成功したファイルのみを一括コミットします...")
        add_proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(TARGET_APP_DIR), "add", "--", *successful_files
        )
        await add_proc.wait()
        commit_proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(TARGET_APP_DIR), "commit", "-m",
            f"nazo_agent: Aider自律修正 ({success_count}/{len(tasks)}件成功)"
        )
        await commit_proc.wait()

    # Phase 4: 最終監査 (CI再実行)
    await phase1_audit(is_final=True)

    print("\n" + "🌟"*25)
    print("🎯 【V8.1 対話型・自律パイプライン完走】")
    print("  実行元プロンプト: (ターミナル入力)")
    print("  すべてのフェーズが終了しました。Gitログと final_error_log.txt を確認してください。")
    print("  ※ 万が一、修正に失敗しエラーが悪化していた場合は、以下のコマンドで一撃ロールバックが可能です:")
    print(f"  git -C {TARGET_APP_DIR} reset --hard HEAD~1")
    print("🌟"*25 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V8.1 対話型プロンプト対応・自律パイプライン")
    parser.add_argument("--prompt", type=str, help="Gemini等で作成した要件定義書（Markdown/Text）のパス（省略時は対話モード）")
    args = parser.parse_args()

    instruction = ""
    if args.prompt:
        if not Path(args.prompt).exists():
            print(f"🚨 エラー: ファイルが見つかりません -> {args.prompt}")
            sys.exit(1)
        with open(args.prompt, "r", encoding="utf-8") as f:
            instruction = f.read()
    else:
        print("\n" + "="*50)
        print("🤖 【Nazo-Agent V8.1】 修正指示を入力してください。")
        print("   (※入力を完了するには、空行で Enter を2回連続で押してください)")
        print("="*50)
        lines = []
        while True:
            try:
                line = input()
                if line == "" and (not lines or lines[-1] == ""):
                    break
                lines.append(line)
            except KeyboardInterrupt:
                print("\n🛑 入力がキャンセルされました。")
                sys.exit(0)
            except EOFError:
                break
        instruction = "\n".join(lines).strip()

    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    if instruction:
        asyncio.run(main_flow(instruction))
    else:
        print("🛑 実行がキャンセルされました（入力なし）。")
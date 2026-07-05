import asyncio
import os
import sys
import json
import ssl
from pathlib import Path
from dotenv import load_dotenv

# Windowsのデフォルトコンソール(cp932)では絵文字の print が UnicodeEncodeError で
# クラッシュするため、明示的にUTF-8へ固定する。
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# APIクライアント
from google import genai
from google.genai import types
from pydantic import BaseModel

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

async def run_linter(tool_name: str) -> str:
    """単一のLintツールを非同期サブプロセスで実行し、生ログを抽出する（タイムアウト防弾版）"""
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
            return f"### ツール: {tool_name.upper()} (🚨 タイムアウト: 60秒超過で強制終了)\n```text\nプロセスがハングアップしました。\n```\n"
            
        out_text = stdout.decode('utf-8', errors='replace')
        err_text = stderr.decode('utf-8', errors='replace')
        output = (out_text + "\n" + err_text).strip()
        
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

async def phase1_audit() -> Path:
    """フェーズ1: 4ツールの完全非同期実行"""
    print(f"🔍 [Phase 1] ターゲット環境 ({TARGET_APP_DIR.name}/{TARGET_CODE_DIR}) の静的解析を非同期で開始します...")
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
    out_file = audit_dir / "error_log.txt"
    
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
        
    print(f"🎉 フェーズ1完了: ファクトレポートを生成しました -> {out_file}")
    return out_file

async def phase2_triage(error_log_path: Path) -> dict:
    """フェーズ2: Gemini APIを用いたトリアージとソースコード抽出"""
    print("\n🔍 [Phase 2] Gemini 3.5 Flash によるエラーログのトリアージと抽出を開始します...")
    api_key = os.getenv("GEMINI_API_KEY")
    # Phase 3と同じNorton SSLインスペクション対策。ただし google-genai SDK は
    # client_args["verify"] が bool False だと「未設定」とみなして自前の厳格な
    # SSLContext で上書きしてしまう(_api_client.py の `if not ctx` 判定がFalseを
    # falsyとして扱うバグ的挙動を実機ソース確認済み)。そのため bool ではなく
    # 検証を無効化した ssl.SSLContext オブジェクト自体を渡す必要がある。
    _insecure_ctx = ssl.create_default_context()
    _insecure_ctx.check_hostname = False
    _insecure_ctx.verify_mode = ssl.CERT_NONE
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            client_args={"verify": _insecure_ctx, "trust_env": True}
        ),
    )
    
    with open(error_log_path, "r", encoding="utf-8") as f:
        error_log = f.read()

    prompt = f"""
以下の静的解析エラーログから、Aiderによる自動修正が【本当に必要な致命的エラー】を含むファイルを特定し、
ファイルごとに Aider が迷わず修正に着手できる具体的かつ明確な指示（instruction）を生成してください。

【厳格な抽出条件】
1. Mypyの重大な型不整合や、Banditの致命的なセキュリティリスク、Radonの複雑度超過（保守性の危機）のみを対象とすること。
2. Ruffによる「未使用のインポート(F401)」「1行の複数ステートメント(E701)」「インポート順序(I001)」などの【軽微なスタイル違反・フォーマット違反】は絶対に対象から除外すること。
3. テスト用の一時ファイル（_temp_*.py 等）は無視すること。
4. instruction には、対象ファイルのどの関数・箇所を、なぜ、どのように直すべきかを具体的に記述し、
   Aiderがソースコードを見ずとも着手できるレベルの明確さを持たせること。

エラーログ:
{error_log}
"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model='gemini-3.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=TriageResult,
                    temperature=0.0
                )
            )
            result_json = json.loads(response.text)
            break
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"🚨 Phase 2 抽出エラー: {str(e)}")
                sys.exit(1)
            await asyncio.sleep(3 * (2 ** attempt))

    tasks = result_json.get("tasks", [])
    print("\n" + "="*50)
    print("📋 【Gemini トリアージ抽出結果（ターミナル表示）】")
    print(f" ［修正対象タスク数］: {len(tasks)} 件")
    for idx, task in enumerate(tasks, 1):
        print(f"   {idx}. {task.get('file_path', '不明なパス')}")
        print(f"      指示: {task.get('instruction', '記述なし')}")
    print("\n ［トリアージ・サマリー］:")
    print(f"  {result_json.get('summary', '記述なし')}")
    print("="*50 + "\n")

    triage_path = BASE_DIR / "audit_reports" / "triage_result.json"
    
    with open(triage_path, "w", encoding="utf-8") as f:
        json.dump(result_json, f, indent=2, ensure_ascii=False)
        
    print(f"✅ フェーズ2完了: 高純度コンテキストを保存しました -> {triage_path}")
    return result_json

async def phase3_aider_execution(tasks: list[dict]) -> None:
    """フェーズ3: Aiderサブプロセスを直列起動し、タスクを1件ずつ個別に撃破する(Map-Reduce方式)"""
    print(f"\n🔍 [Phase 3] Aider による個別ファイル修正を開始します (対象: {len(tasks)} 件)...")

    if not tasks:
        print("✅ フェーズ3完了: 修正対象タスクが0件のため、Aiderの起動をスキップしました。")
        return

    # .envの手入力ミス（余分な空白・改行の混入）を吸収し、サブプロセスへクリーンな
    # 状態で引き継ぐ。os.environ自体は書き換えず、コピーの上で上書きすることで
    # 親プロセス自身の環境を汚さない。
    clean_env = os.environ.copy()
    clean_env["ANTHROPIC_API_KEY"] = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    clean_env["GEMINI_API_KEY"] = (os.getenv("GEMINI_API_KEY") or "").strip()
    # Aiderサブプロセス側のcp932起因UnicodeEncodeErrorを防ぐため、子プロセスの
    # 標準入出力エンコーディングを強制的にUTF-8へ固定する。
    clean_env["PYTHONIOENCODING"] = "utf-8"
    clean_env["PYTHONUTF8"] = "1"

    success_count = 0
    failure_count = 0

    for idx, task in enumerate(tasks, 1):
        file_path = task.get("file_path", "")
        instruction = task.get("instruction", "")
        target_file = TARGET_APP_DIR / file_path

        print(f"\n{'='*50}")
        print(f"🛠️  [{idx}/{len(tasks)}] Aider起動: {file_path}")
        print(f"   指示: {instruction}")
        print(f"{'='*50}")

        if not target_file.exists():
            print(f"⚠️ 警告: 対象ファイルが存在しません。スキップします -> {target_file}")
            failure_count += 1
            print("🚨 サーキットブレーカー発動: カスケード障害（依存関係の破壊連鎖）を防ぐため、後続のタスクを安全に遮断（Abort）しました。")
            break

        cmd = [
            "aider",
            "--yes",
            "--no-verify-ssl",
            "--message", instruction,
            str(target_file),
        ]

        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(TARGET_APP_DIR),
                env=clean_env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300.0)
            except asyncio.TimeoutError:
                process.kill()
                print(f"🚨 タイムアウト: {file_path} の修正が300秒を超過したため強制終了しました。")
                failure_count += 1
                print("🚨 サーキットブレーカー発動: カスケード障害（依存関係の破壊連鎖）を防ぐため、後続のタスクを安全に遮断（Abort）しました。")
                break

            output = (stdout.decode("utf-8", errors="replace") + "\n" + stderr.decode("utf-8", errors="replace")).strip()

            if process.returncode == 0:
                print(f"✅ 完了: {file_path}")
                success_count += 1
            else:
                print(f"⚠️ Aiderが異常終了しました (code={process.returncode}): {file_path}")
                if output:
                    print(f"```text\n{output}\n```")
                failure_count += 1
                print("🚨 サーキットブレーカー発動: カスケード障害（依存関係の破壊連鎖）を防ぐため、後続のタスクを安全に遮断（Abort）しました。")
                break

        except Exception as e:
            if process is not None and process.returncode is None:
                process.kill()
            print(f"🚨 実行エラー ({file_path}): {type(e).__name__} - {str(e)}")
            failure_count += 1
            print("🚨 サーキットブレーカー発動: カスケード障害（依存関係の破壊連鎖）を防ぐため、後続のタスクを安全に遮断（Abort）しました。")
            break

    print(f"\n🎉 フェーズ3完了: 成功 {success_count} 件 / 失敗 {failure_count} 件 (全 {len(tasks)} 件)")

async def main_flow():
    load_dotenv(BASE_DIR / ".env")
    gemini_key = os.getenv("GEMINI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    
    if not gemini_key or not anthropic_key:
        print("🚨 致命的エラー: GEMINI_API_KEY または ANTHROPIC_API_KEY が .env に設定されていません。")
        sys.exit(1)

    log_path = await phase1_audit()
    if log_path and log_path.exists():
        triage_data = await phase2_triage(log_path)
        await phase3_aider_execution(triage_data.get("tasks", []))

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main_flow())
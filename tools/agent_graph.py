"""
tools/agent_graph.py
======================
Nazo-Agent: LangGraphによる自律修復ループ(Feature 1.x / Epic 1 VRAM防弾化)。

RTX 4060(VRAM 8GB)の物理制約と、複数モデル切り替えによるI/Oスラッシングを回避する
ため、通常の障害対応(Hot Loop)は qwen2.5-coder:7b 単一モデルのみを常駐させ、
「現場監督(エラーログ解析)」→「職人(AST置換用JSON出力)」の2ロールをプロンプト
切り替えのみで演じ分けるシングルモデル・マルチロール体制を採る(Hot Loop内での
モデルのアンロード/ロード切り替えは絶対に行わない)。

7Bクラスの小型モデルはJSON出力を崩しやすいため、職人ロールには
(1) 正しい出力例のFew-shot注入、(2) Pydantic検証失敗時に最大MAX_JSON_RETRIES回
エラー内容を提示して再試行させるRetryループ、の2段の防弾機構を組み込む。
このRetryループがMAX_JSON_RETRIES回失敗した場合のみ、サーキットブレーカーが
作動してQwenのHot Loopを強制終了し、Gemma(gemma4:12b)への最終エスカレーション
ノードへ遷移する。この遷移時のみ、明示的にkeep_alive=0でQwenをアンロードして
VRAMを解放してからGemmaをロードする排他制御を行う(I/Oペナルティはこの
エスカレーション経路でのみ許容する)。Gemmaは「なぜQwenが解決できなかったか」を
分析し、結果をデッドレターとして保存した上で、以後の自動処理を安全に一時停止
(Suspend)し、Claudeや人間へのエスカレーションに委ねる。

検証済みJSONの実際の適用(libcstによる安全なAST置換とアトミック書き込み)は、
tools/ast_modifier.py をサブプロセスとして呼び出すことで委譲する
(apply_modification()はFatalな検証失敗時にsys.exit(1)する設計のため、
このLangGraphプロセス自体を巻き込まないようプロセス分離を維持する)。

対象モデル: qwen2.5-coder:7b (Hot Loop) / gemma4:12b (最終エスカレーション)。
いずれもOllamaへ `ollama pull <model>` 済みであること。
"""

import datetime
import json
import operator
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Annotated, TypedDict

import ollama
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from tools.ast_modifier import AstModificationInstruction

MAX_JSON_RETRIES = 3
OLLAMA_MODEL = "qwen2.5-coder:7b"
GEMMA_MODEL = "gemma4:12b"
BASE_DIR = Path(__file__).resolve().parent.parent
DEAD_LETTER_DIR = BASE_DIR / "tools" / "audit_reports" / "dead_letters"

# 【VRAM 8GB防弾】複数モデルの同時常駐・切り替えは絶対に行わない。現場監督/職人の
# 両ロールとも、この単一インスタンスをプロンプト切り替えのみで演じ分ける
# (シングルモデル・マルチロール)。
llm = ChatOllama(model=OLLAMA_MODEL, temperature=0.1)

# 【最終エスカレーション専用】サーキットブレーカー作動時にのみ呼び出す。
# keep_alive=0により、Gemmaの推論完了直後に即座にVRAMを解放し、次回のQwen
# Hot Loopのために明け渡す(常駐させない)。
gemma_llm = ChatOllama(model=GEMMA_MODEL, temperature=0.1, keep_alive=0)


CRAFTSMAN_FEWSHOT_EXAMPLE = """\
【出力フォーマットの例(Few-shot)】
以下はあなたが出力すべきJSONの正しい例です。このフォーマットに厳密に従ってください。

```json
{
  "file_path": "apps/evaluator/backend/main.py",
  "target_name": "health_check",
  "new_code": "async def health_check():\\n    return {\\"status\\": \\"ok\\"}\\n",
  "triage_type": "bug_fix"
}
```

- file_path: 修正対象ファイルのパス(文字列)。
- target_name: 置換対象の関数名またはクラス名(完全一致・文字列)。
- new_code: 置換後の関数/クラス定義の完全なソースコード(文字列。改行は\\nでエスケープ)。
- triage_type: "bug_fix" または "test_update" のいずれか。
説明文やMarkdownのコードフェンスは一切付けず、上記のJSONオブジェクト本体のみを出力すること。
"""


class AuditState(TypedDict):
    file_path: str
    current_code: str
    error_log: str
    audit_history: Annotated[list[str], operator.add]
    diagnosis: str
    retry_count: int
    last_validation_error: str
    raw_json_text: str
    result_message: str
    escalated: bool
    dead_letter_path: str


def _extract_text(response) -> str:
    """ChatOllamaの応答(AIMessage等)からテキスト本文を取り出す。"""
    content = getattr(response, "content", response)
    return content if isinstance(content, str) else str(content)


def _strip_code_fence(text: str) -> str:
    """LLMがMarkdownのコードフェンス(```json ... ```)を付けてきた場合の安全策として除去する。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if lines and lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def supervisor_node(state: AuditState) -> dict:
    """【現場監督ロール】エラーログ(あれば)と対象ファイルを解析し、原因と修正方針を
    診断する。この段階では修正コードそのものは書かない。"""
    error_log = (state.get("error_log") or "").strip()
    if error_log:
        prompt = (
            "あなたは経験豊富な現場監督です。以下の「エラーログ」と対象ファイルの"
            "現在のコードを確認し、エラーの原因と、どの関数/クラスをどのように"
            "修正すべきかを簡潔に診断してください。この段階では修正コードそのものは"
            "書かず、診断結果のみを述べてください。\n\n"
            f"【エラーログ】\n{error_log}\n\n"
            f"【対象ファイル: {state['file_path']}】\n```python\n{state['current_code']}\n```"
        )
    else:
        prompt = (
            "あなたは経験豊富な現場監督です。以下のコードを読み、"
            "バグ・型不整合・未使用インポート等の問題点を診断してください。"
            "この段階では修正コードそのものは書かず、診断結果のみを述べてください。"
            "問題が無ければ「問題なし」と診断してください。\n\n"
            f"```python\n{state['current_code']}\n```"
        )
    diagnosis = _extract_text(llm.invoke(prompt))
    return {
        "diagnosis": diagnosis,
        "audit_history": [f"[現場監督] {diagnosis}"],
    }


def craftsman_node(state: AuditState) -> dict:
    """【職人ロール】現場監督の診断に基づき、AST置換用の修正指示を厳密なJSON形式で
    1つだけ出力する。前回の試行でスキーマ検証に失敗している場合は、そのエラー内容を
    プロンプトへ明示的に含めて再出力させる(Retryループの実体)。"""
    retry_note = ""
    if state.get("last_validation_error"):
        retry_note = (
            f"\n\n【前回の出力エラー(必ず修正すること)】\n{state['last_validation_error']}\n"
            "上記のスキーマ違反・JSON構文エラーを修正し、正しいJSONのみを再度出力してください。"
        )

    prompt = (
        "あなたは腕利きの職人です。現場監督の診断結果に基づき、AST置換用の修正指示を"
        "厳密なJSON形式で1つだけ出力してください。\n\n"
        f"{CRAFTSMAN_FEWSHOT_EXAMPLE}\n"
        f"【現場監督の診断】\n{state['diagnosis']}\n\n"
        f"【対象ファイル: {state['file_path']}】\n```python\n{state['current_code']}\n```"
        f"{retry_note}"
    )
    raw = _extract_text(llm.invoke(prompt)).strip()
    return {
        "raw_json_text": raw,
        "audit_history": [f"[職人] JSON出力(試行{state['retry_count'] + 1}回目)"],
    }


def validate_node(state: AuditState) -> dict:
    """職人が出力したJSON文字列をパース・Pydantic検証する(実際のファイル書き込みは
    まだ行わない)。失敗時はretry_countを進め、次の職人ノード呼び出しへ誤りを申し送る。"""
    raw = _strip_code_fence(state["raw_json_text"])
    try:
        parsed = json.loads(raw)
        AstModificationInstruction(**parsed)
    except (json.JSONDecodeError, ValidationError) as e:
        next_retry = state["retry_count"] + 1
        return {
            "last_validation_error": str(e),
            "retry_count": next_retry,
            "audit_history": [f"[検証] スキーマ検証エラー(試行{next_retry}回目): {e}"],
        }
    return {
        "last_validation_error": "",
        "audit_history": ["[検証] スキーマ検証OK"],
    }


def _route_after_validate(state: AuditState) -> str:
    if not state.get("last_validation_error"):
        return "apply"
    if state["retry_count"] >= MAX_JSON_RETRIES:
        return "gemma_fallback"
    return "craftsman"


def apply_node(state: AuditState) -> dict:
    """検証済みJSONを tools/ast_modifier.py へサブプロセスとして委譲し、実際の
    AST置換・アトミック書き込みを行わせる。

    apply_modification()はセマンティック差分検証等のFatalな失敗時にsys.exit(1)する
    設計のため、常にサブプロセス分離で呼び出し、このLangGraphプロセス自体が
    予期せず落とされることを防ぐ(nazo_agent.pyのClaudeパイプラインと同じ安全策)。
    """
    instruction = json.loads(_strip_code_fence(state["raw_json_text"]))
    # 職人(小型モデル)がfile_pathを取り違えて出力するリスクに備え、実際に適用する
    # ファイルパスは常にrun_self_repair呼び出し時の対象ファイルで上書きする。
    instruction["file_path"] = state["file_path"]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8", errors="strict"
    ) as f:
        json.dump(instruction, f, ensure_ascii=False, indent=2)
        instruction_path = f.name

    try:
        result = subprocess.run(
            ["uv", "run", "python", "tools/ast_modifier.py", instruction_path],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
        )
        output = (result.stdout + "\n" + result.stderr).strip()
    finally:
        Path(instruction_path).unlink(missing_ok=True)

    return {
        "result_message": output,
        "audit_history": [f"[適用] {output}"],
    }


def _unload_qwen() -> None:
    """Gemmaをロードする前にQwenを明示的にアンロードし、VRAM 8GBの排他制御を行う。

    Ollama自体もモデル切り替え時に自動でLRU退避を行うが、keep_alive=0を明示的に
    指定することで確実にVRAMを解放してからGemmaをロードする意図を明確にする。
    このエスカレーション経路以外(Qwenの通常のHot Loop)では絶対に呼ばない。
    失敗してもGemmaフォールバック自体は継続する(ベストエフォート)。
    """
    try:
        ollama.generate(model=OLLAMA_MODEL, prompt="", keep_alive=0)
    except Exception as e:
        print(f"⚠️ [Gemmaフォールバック] Qwenのアンロードに失敗しました(続行します): {e}")


def _write_gemma_dead_letter(
    *,
    file_path: str,
    error_log: str,
    current_code: str,
    audit_history: list[str],
    last_validation_error: str,
    gemma_analysis: str,
) -> Path:
    """Gemmaによる最終分析結果を、tools/nazo_agent.pyの_write_dead_letterと同じ
    命名規則(dead_letter_YYYYMMDD_HHMMSS_UUID.json)でtools/audit_reports/dead_letters/
    へ構造化JSONとして保存する。

    ここに含まれるのはコード・エラーログ・診断テキストのみで、nazo_agent.py側の
    Claude APIペイロード(sanitize_pii対象)のような機密情報は想定していないため、
    PIIサニタイズは意図的に行わない(agent_graph.pyをtools.ast_modifier以外に
    依存させない自己完結の方針を優先する)。
    """
    DEAD_LETTER_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    dead_letter_path = (
        DEAD_LETTER_DIR / f"dead_letter_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    )
    payload = {
        "timestamp": now.isoformat(),
        "file_path": file_path,
        "error_log": error_log,
        "current_code": current_code,
        "qwen_audit_history": audit_history,
        "last_validation_error": last_validation_error,
        "gemma_analysis": gemma_analysis,
    }
    dead_letter_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return dead_letter_path


def gemma_fallback_node(state: AuditState) -> dict:
    """【最終エスカレーション】サーキットブレーカー作動時のみ遷移するノード。

    QwenをVRAMから明示的にアンロードしてから、Gemma(gemma4:12b)を呼び出し、
    エラーログ・対象コード・Qwenの失敗履歴(診断・出力・検証エラー)全体を渡して
    「なぜQwenは解決できなかったのか」を論理的に深く分析させる。分析結果は
    デッドレターとして保存し、以後の自動処理を安全に一時停止(Suspend)して
    Claudeや人間へのエスカレーションに委ねる(このノードはapply_nodeを経由せず、
    ファイルへの書き込みは一切行わない)。
    """
    _unload_qwen()

    failure_history = "\n".join(state["audit_history"])
    prompt = (
        "あなたはシニアソフトウェアアーキテクトです。ローカルの小型モデル"
        f"(qwen2.5-coder:7b)が最大{MAX_JSON_RETRIES}回試行してもこの障害を"
        "自己修復できませんでした。以下のエラーログ・対象コード・Qwenの失敗履歴"
        "(診断結果・生成したJSON・スキーマ検証エラー)を精査し、なぜQwenが"
        "解決できなかったのかを論理的に深く分析してください。人間またはClaudeへの"
        "エスカレーション用レポートとして、根本原因の分析と推奨される次のアクションを"
        "簡潔にまとめてください。\n\n"
        f"【エラーログ】\n{state.get('error_log') or '(なし。汎用コードレビュー)'}\n\n"
        f"【対象ファイル: {state['file_path']}】\n```python\n{state['current_code']}\n```\n\n"
        f"【Qwenの失敗履歴】\n{failure_history}\n\n"
        f"【最終スキーマ検証エラー】\n{state.get('last_validation_error', '')}"
    )
    gemma_analysis = _extract_text(gemma_llm.invoke(prompt))

    dead_letter_path = _write_gemma_dead_letter(
        file_path=state["file_path"],
        error_log=state.get("error_log", ""),
        current_code=state["current_code"],
        audit_history=state["audit_history"],
        last_validation_error=state.get("last_validation_error", ""),
        gemma_analysis=gemma_analysis,
    )

    message = (
        f"🚨 [サーキットブレーカー作動] Qwenが{MAX_JSON_RETRIES}回試行しても"
        "自己修復できなかったため、Hot Loopを遮断してGemmaへ最終エスカレーション"
        "しました。\n"
        f"📮 Gemmaによる分析レポートをデッドレターとして保存しました -> {dead_letter_path}\n"
        "⏸️ 安全のため、このファイルへの自動修正処理を一時停止(Suspend)します。"
        "Claudeまたは人間によるレビューが必要です。"
    )
    return {
        "result_message": message,
        "escalated": True,
        "dead_letter_path": str(dead_letter_path),
        "audit_history": [f"[Gemmaフォールバック] {gemma_analysis}"],
    }


def reporter_node(state: AuditState) -> dict:
    """最終サマリーを出力する(ファイルの実書き込みはapply_nodeが既に完了させている)。"""
    summary_lines = [
        "=== Nazo-Agent 自律修復ループ(Qwen 7B 単一モデル・マルチロール) 完了報告 ===",
        f"対象ファイル: {state['file_path']}",
        f"職人ノードのリトライ回数: {state['retry_count']}",
    ]
    if state.get("escalated"):
        summary_lines.append("⚠️ Gemmaへの最終エスカレーションが発生しました。")
        summary_lines.append(f"デッドレター: {state.get('dead_letter_path', '')}")
    summary_lines += [
        "--- 履歴 ---",
        *state["audit_history"],
        "--- 最終結果 ---",
        state.get("result_message", ""),
    ]
    summary = "\n".join(summary_lines)
    print(summary)
    return {"audit_history": [f"[Reporter] {summary}"]}


def build_graph():
    graph = StateGraph(AuditState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("craftsman", craftsman_node)
    graph.add_node("validate", validate_node)
    graph.add_node("apply", apply_node)
    graph.add_node("gemma_fallback", gemma_fallback_node)
    graph.add_node("reporter", reporter_node)

    graph.set_entry_point("supervisor")
    graph.add_edge("supervisor", "craftsman")
    graph.add_edge("craftsman", "validate")
    # 検証成功なら適用へ、失敗かつリトライ余地があれば職人ノードへ差し戻し、
    # リトライを使い果たしたらサーキットブレーカーが作動してGemmaフォールバックへ。
    graph.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"apply": "apply", "craftsman": "craftsman", "gemma_fallback": "gemma_fallback"},
    )
    graph.add_edge("apply", "reporter")
    graph.add_edge("gemma_fallback", "reporter")
    graph.add_edge("reporter", END)

    return graph.compile()


def run_self_repair(file_path: str, error_log: str = "") -> dict:
    """指定ファイルに対し、Qwen 7B単一モデルのマルチロール自律修復ループ
    (現場監督で診断→職人がAST置換用JSONを出力[最大MAX_JSON_RETRIES回リトライ]→適用)
    を1回だけ実行する(旧実装にあった「全体を再スキャンしてCLEAN判定するまで繰り返す」
    という外側ループは、JSON置換方式とは相性が悪いため廃止した)。

    error_log: 診断対象のエラーログ本文。省略時は現場監督が対象ファイル全体の
    汎用コードレビューを行う。
    """
    path = Path(file_path)
    source = path.read_text(encoding="utf-8", errors="strict")

    app = build_graph()
    initial_state: AuditState = {
        "file_path": str(path),
        "current_code": source,
        "error_log": error_log,
        "audit_history": [],
        "diagnosis": "",
        "retry_count": 0,
        "last_validation_error": "",
        "raw_json_text": "",
        "result_message": "",
        "escalated": False,
        "dead_letter_path": "",
    }
    return app.invoke(initial_state)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python tools/agent_graph.py <target_file>")
        sys.exit(1)
    run_self_repair(sys.argv[1])

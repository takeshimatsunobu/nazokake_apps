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

import contextlib
import datetime
import json
import operator
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Annotated, TypedDict

import anthropic
import httpx
import ollama
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from tools.ast_modifier import AstModificationInstruction
from tools.compile_knowledge import extract_keywords
from tools.config import settings
from tools.knowledge_retriever import record_experience, retrieve_experiences

MAX_JSON_RETRIES = 3
OLLAMA_MODEL = "qwen2.5-coder:7b"
GEMMA_MODEL = "gemma4:12b"
CTO_MODEL = "claude-sonnet-5"
BASE_DIR = Path(__file__).resolve().parent.parent
DEAD_LETTER_DIR = BASE_DIR / "tools" / "audit_reports" / "dead_letters"
PR_DRAFT_DIR = BASE_DIR / "tools" / "audit_reports" / "pr_drafts"
SSOT_PATH = BASE_DIR / "SSoT_architecture.md"
BENCHMARK_REPORTS_DIR = BASE_DIR / "tools" / "benchmark" / "reports"

# tools/nazo_agent.pyと同様、cto_node()のANTHROPIC_API_KEY(os.getenv経由)がインポート
# 時点で確実にos.environへ反映されるよう、ここで明示的に.envを読み込む
# (tools.config.settingsはpydantic-settings内部でのみ.envを解決し、os.environへは
# 一部の値[OLLAMA_HOST]しか反映しないため、これとは別に必要)。
load_dotenv(BASE_DIR / ".env")

# 【VRAM 8GB防弾】複数モデルの同時常駐・切り替えは絶対に行わない。現場監督/職人の
# 両ロールとも、この単一インスタンスをプロンプト切り替えのみで演じ分ける
# (シングルモデル・マルチロール)。
llm = ChatOllama(model=OLLAMA_MODEL, temperature=0.1)

# 【Constrained Decoding】7Bクラスの小型モデル特有のJSON構造崩れを、Few-shotのような
# 「お願い」ではなく、Ollamaのネイティブな文法制約付き生成(format=JSON Schema)で
# 物理的に排除する。職人ロール専用にformatをbindした別インスタンスを用意し、現場監督
# ロール(自由記述の診断テキストを出力する`llm`本体)には一切影響させない。
# langchain_ollama.ChatOllama.with_structured_output(method="json_schema")は内部で
# 全く同じ self.bind(format=schema.model_json_schema()) を行う(1.1.0のソースで確認済み)
# ため、ここではより直接的な等価実装を採用し、validate_node以降の既存の
# raw_json_text文字列パース+リトライ契約(MAX_JSON_RETRIES)を一切変えずに済む。
craftsman_llm = llm.bind(format=AstModificationInstruction.model_json_schema())

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
  "triage_type": "bug_fix",
  "confidence_score": 0.95,
  "requires_escalation": false
}
```

- file_path: 修正対象ファイルのパス(文字列)。
- target_name: 置換対象の関数名またはクラス名(完全一致・文字列)。
- new_code: 置換後の関数/クラス定義の完全なソースコード(文字列。改行は\\nでエスケープ)。
- triage_type: "bug_fix" または "test_update" のいずれか。
- confidence_score: この修正案そのものの正しさに対する自己評価(0.0〜1.0)。診断が明確で
  修正が単純明快なら1.0に近い値、原因が複数考えられる・複数ファイルへの影響が疑われる・
  対象コードの意図が読み取りにくい等、少しでも不確実な点があれば0.8未満の低い値にすること。
  安易に高い値を申告してはならない(過信は禁止)。
- requires_escalation: 上記confidence_scoreが低い場合、または診断結果に複数の解釈が
  あり得る・アーキテクチャ全体に関わる判断が必要と感じる場合はtrueにすること。trueの場合、
  この修正案はそのまま適用されず、人間よりも上位のクラウドモデル(CTO)がレビューする。
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
    # --- CTOエスカレーション(内容面の不確実性、gemma_fallbackとは独立した経路) ---
    requires_cto_escalation: bool
    cto_instruction: dict
    cto_escalated: bool
    pr_draft_path: str
    escalation_branch: str


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
    プロンプトへ明示的に含めて再出力させる(Retryループの実体)。

    出力形式自体はcraftsman_llm(Constrained Decoding、format=AstModificationInstruction
    のJSON Schema)がOllama側で文法的に強制するが、モデルに「どう考えさせるか」の質を
    保つため、Few-shotプロンプト(CRAFTSMAN_FEWSHOT_EXAMPLE)の静的注入は維持する
    (文法制約は出力の構文を保証するだけで、意味的に正しい修正内容までは保証しない)。
    """
    retry_note = ""
    if state.get("last_validation_error"):
        retry_note = (
            f"\n\n【前回の出力エラー(必ず修正すること)】\n{state['last_validation_error']}\n"
            "上記のスキーマ違反・JSON構文エラーを修正し、正しいJSONのみを再度出力してください。"
        )

    prompt = (
        "あなたは腕利きの職人です。現場監督の診断結果に基づき、AST置換用の修正指示を"
        "厳密なJSON形式で1つだけ出力してください。修正内容そのものへの自信の度合いを"
        "confidence_score/requires_escalationとして必ず誠実に自己申告してください"
        "(過信して高い自信度を申告してはいけません)。\n\n"
        f"{CRAFTSMAN_FEWSHOT_EXAMPLE}\n"
        f"【現場監督の診断】\n{state['diagnosis']}\n\n"
        f"【対象ファイル: {state['file_path']}】\n```python\n{state['current_code']}\n```"
        f"{retry_note}"
    )
    raw = _extract_text(craftsman_llm.invoke(prompt)).strip()
    return {
        "raw_json_text": raw,
        "audit_history": [f"[職人] JSON出力(試行{state['retry_count'] + 1}回目)"],
    }


def validate_node(state: AuditState) -> dict:
    """職人が出力したJSON文字列をパース・Pydantic検証する(実際のファイル書き込みは
    まだ行わない)。失敗時はretry_countを進め、次の職人ノード呼び出しへ誤りを申し送る。

    スキーマ検証(形式面)に成功した場合でも、Qwen自身が自己申告したconfidence_score/
    requires_escalationを見て、内容面の不確実性が高いと判断した場合はrequires_cto_escalation
    を立てる(gemma_fallbackのサーキットブレーカーとは独立した、別のエスカレーション経路)。
    """
    raw = _strip_code_fence(state["raw_json_text"])
    try:
        parsed = json.loads(raw)
        validated = AstModificationInstruction(**parsed)
    except (json.JSONDecodeError, ValidationError) as e:
        next_retry = state["retry_count"] + 1
        return {
            "last_validation_error": str(e),
            "retry_count": next_retry,
            "audit_history": [f"[検証] スキーマ検証エラー(試行{next_retry}回目): {e}"],
        }

    requires_cto_escalation = validated.requires_escalation or (
        validated.confidence_score < settings.escalation_confidence_threshold
    )
    audit_entry = (
        f"[検証] スキーマ検証OK(confidence_score={validated.confidence_score}, "
        f"requires_escalation={validated.requires_escalation})"
    )
    if requires_cto_escalation:
        audit_entry += " -> CTOエスカレーション対象"
    return {
        "last_validation_error": "",
        "requires_cto_escalation": requires_cto_escalation,
        "audit_history": [audit_entry],
    }


def _route_after_validate(state: AuditState) -> str:
    if not state.get("last_validation_error"):
        if state.get("requires_cto_escalation"):
            return "cto_node"
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


def _load_ssot_context() -> str:
    """SSoT_architecture.mdの内容を読み込む(存在しない場合は空文字を返す)。"""
    try:
        return SSOT_PATH.read_text(encoding="utf-8", errors="strict")
    except (FileNotFoundError, OSError):
        return ""


def _build_experience_replay_block(state: "AuditState") -> str:
    """現在のエラーログ・Qwenの診断・自己申告内容から検索クエリを組み立て、
    tools/knowledge_retriever.pyで過去の指示書のうち関連度上位の教訓を検索し、
    CTOプロンプトの動的ブロックへ注入する文字列を組み立てる。

    知識ベース未ビルド・検索失敗等でこの処理自体が失敗しても、CTOエスカレーション
    フロー全体を巻き込んで失敗させない(ベストエフォート、失敗時は「見つからなかった」
    扱いにフォールバックする)。
    """
    query = "\n".join(
        filter(
            None,
            [
                state.get("error_log", ""),
                state.get("diagnosis", ""),
                state.get("raw_json_text", ""),
            ],
        )
    )
    try:
        experiences = retrieve_experiences(query, top_k=3)
    except Exception as e:  # noqa: BLE001 - RAGの失敗でCTOエスカレーションを止めない
        print(f"⚠️ [Experience Replay] 過去の教訓の検索に失敗しました(無視して続行): {e}")
        experiences = []

    if not experiences:
        return "(該当する過去の教訓は見つかりませんでした。)"
    return "\n".join(
        f"- [instructions/{exp.get('id')}] {exp.get('summary', '')} "
        f"(参照: {exp.get('filepath', '')})"
        for exp in experiences
    )


def _build_cto_client() -> anthropic.Anthropic:
    """CTOエスカレーション専用のAnthropicクライアントを構築する。

    tools/nazo_agent.pyの既存パターン(TLS問題を防ぐ防弾設定としてverify=False,
    trust_env=Trueのhttpx.Clientを明示的に渡す)を踏襲する。agent_graph.py自体は
    同期実装のため、AsyncAnthropicではなく同期のAnthropicクライアントを使う。
    """
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    http_client = httpx.Client(
        verify=False, trust_env=True, timeout=httpx.Timeout(600.0, connect=30.0)
    )
    return anthropic.Anthropic(api_key=api_key, http_client=http_client, max_retries=0)


def _write_cto_dead_letter(*, state: AuditState, error: str) -> Path:
    """CTOエスカレーション自体が失敗した場合(API例外・ツール未呼び出し・スキーマ検証
    失敗)の記録。tools/nazo_agent.pyの_write_dead_letterと同じ命名規則を用いる。
    """
    DEAD_LETTER_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    dead_letter_path = (
        DEAD_LETTER_DIR
        / f"dead_letter_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    )
    payload = {
        "timestamp": now.isoformat(),
        "file_path": state["file_path"],
        "error_log": state.get("error_log", ""),
        "current_code": state["current_code"],
        "qwen_audit_history": state.get("audit_history", []),
        "qwen_raw_json_text": state.get("raw_json_text", ""),
        "cto_error": error,
    }
    dead_letter_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return dead_letter_path


def cto_node(state: AuditState) -> dict:
    """【CTOエスカレーション】Qwenが自己申告した不確実性(confidence_score不足/
    requires_escalation)を受けて、クラウド上位モデル(Claude)へ修正案の生成・レビューを
    委譲する。

    システムプロンプト+SSoT_architecture.mdを結合した「静的ブロック」の末尾に
    cache_control(ephemeral)を付与し、その後続のuserメッセージへ動的なエラーログ・
    対象コード・Qwenの診断履歴を配置する(静的ブロックを先に確定させ、動的コンテンツを
    後方に置くことでPrompt Cachingのヒット率を最大化する設計。nazo_agent.pyの既存の
    Claude連携と同じ配置)。この動的ブロックには、tools/knowledge_retriever.pyによる
    軽量ローカルRAG(Dynamic Experience Replay)で検索した、過去の指示書のうち今回の
    エラーログ・診断内容と関連性が高い上位数件の教訓も注入する(全履歴を詰め込む
    アプローチは厳禁のため、関連度上位のみに絞る)。

    このノード自身はファイルへの書き込みを一切行わない(実際の適用はsandbox_verify_node
    が隔離ブランチ上でのみ行う)。
    """
    client = _build_cto_client()
    ssot_context = _load_ssot_context()
    experience_replay_block = _build_experience_replay_block(state)

    system_prompt = (
        "あなたはシニアソフトウェアアーキテクト兼CTOです。ローカルの小型モデル"
        "(qwen2.5-coder:7b)が生成した修正案について、モデル自身の確信度が低い"
        "(confidence_score不足、またはrequires_escalation=Trueの自己申告)ため、"
        "レビューと改善案の提示を求められています。\n\n"
        "【絶対的仕様書(SSoT)】\n"
        f"{ssot_context if ssot_context else '(SSoT_architecture.md が存在しないため、SSoTは提供されていません。要件定義書とエラーログのみを根拠に判断してください。)'}"
    )
    system_blocks = [
        {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
    ]

    dynamic_content = (
        f"【エラーログ】\n{state.get('error_log') or '(なし。汎用コードレビュー)'}\n\n"
        f"【対象ファイル: {state['file_path']}】\n```python\n{state['current_code']}\n```\n\n"
        f"【現場監督(Qwen)の診断】\n{state.get('diagnosis', '')}\n\n"
        "【職人(Qwen)の生成した修正案とその自己評価】\n"
        f"{_strip_code_fence(state.get('raw_json_text', ''))}\n\n"
        "【過去の関連する教訓 (Experience Replay)】\n"
        f"{experience_replay_block}\n\n"
        "上記の修正案はQwen自身が不確実性を申告しています。SSoTと実際のコードを踏まえて"
        "この修正が正しいかどうかを精査し、必要であれば改善したAST置換指示を"
        "submit_fix ツールの呼び出しのみで提出してください。"
    )
    messages: list = [
        {"role": "user", "content": [{"type": "text", "text": dynamic_content}]}
    ]

    submit_tool = {
        "name": "submit_fix",
        "description": "レビュー済みの、libcstによる安全なAST置換指示を1件提出する。",
        "input_schema": AstModificationInstruction.model_json_schema(),
    }

    try:
        response = client.messages.create(
            model=CTO_MODEL,
            max_tokens=8192,
            system=system_blocks,
            messages=messages,
            tools=[submit_tool],
            tool_choice={"type": "tool", "name": "submit_fix"},
        )
        submit_block = next(
            (
                b
                for b in response.content
                if getattr(b, "type", "") == "tool_use" and b.name == "submit_fix"
            ),
            None,
        )
        if submit_block is None:
            raise ValueError("submit_fix ツールの呼び出しが得られませんでした。")

        validated = AstModificationInstruction(**submit_block.input)
        # 職人(小型モデル)と同じ防御: file_pathは常に対象ファイルで上書きする。
        instruction = validated.model_dump()
        instruction["file_path"] = state["file_path"]

        message = (
            f"🧑‍💼 [CTOエスカレーション] Claude({CTO_MODEL})による修正案を取得しました。"
            "このまま直接適用せず、隔離ブランチでのサンドボックス検証へ進みます。"
        )
        return {
            "cto_instruction": instruction,
            "cto_escalated": True,
            "result_message": message,
            "audit_history": [f"[CTO] {message}"],
        }
    except Exception as e:  # noqa: BLE001 - API例外全般を安全にデッドレターへ回収する
        dead_letter_path = _write_cto_dead_letter(state=state, error=str(e))
        message = (
            f"🚨 [CTOエスカレーション失敗] Claudeへの問い合わせ・修正案の検証に"
            f"失敗しました: {e}\n"
            f"📮 デッドレターとして保存しました -> {dead_letter_path}\n"
            "⏸️ 安全のため、このファイルへの自動修正処理を一時停止(Suspend)します。"
        )
        return {
            "cto_escalated": True,
            "dead_letter_path": str(dead_letter_path),
            "result_message": message,
            "audit_history": [f"[CTO] {message}"],
        }


def _route_after_cto(state: AuditState) -> str:
    if state.get("cto_instruction"):
        return "sandbox_verify"
    return "reporter"


def _find_git_repo_root(file_path: str) -> Path:
    """file_pathから親方向に.gitを探索し、実際に属するgitリポジトリのルートを特定する。

    ルートのモノレポ(tools/等)と、ネストした別git管理下のapps/evaluator/apps/batch_factory
    の両方に対応するため、BASE_DIR固定ではなく動的に解決する。見つからない場合はBASE_DIRへ
    フォールバックする。
    """
    current = Path(file_path).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return BASE_DIR


@contextlib.contextmanager
def managed_git_worktree(repo_root: Path):
    """隔離用の一時 git worktree を UUID 名前空間で作成し、ブロック終了時に必ず物理
    ディレクトリを破棄するコンテキストマネージャ。

    ブランチ名を `escalation/issue-{unixtime}-{uuid4().hex}` として一意化することで、
    同時に複数のエスカレーションが走っても worktree パス/ブランチ名が衝突しない。
    worktree の作成に失敗した場合は RuntimeError を送出する(この時点ではまだ
    worktree が存在しないため、finally での破棄処理には入らない)。作成に成功した
    後は、yield 先(呼び出し元)の処理が正常終了・例外のいずれであっても、finally で
    `git worktree remove --force` を実行して物理ディレクトリを必ずパージする
    (レビュー用に残すのはブランチのみで、worktree自体は使い捨てとする)。
    """
    branch_name = f"escalation/issue-{int(time.time())}-{uuid.uuid4().hex}"
    worktree_path = Path(tempfile.mkdtemp(prefix="nazo_escalation_")) / branch_name.replace(
        "/", "_"
    )
    result_add = subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(worktree_path), "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result_add.returncode != 0:
        raise RuntimeError(
            f"隔離ブランチ/worktreeの作成に失敗しました: {result_add.stderr.strip()}"
        )
    try:
        yield worktree_path, branch_name
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )


def _run_benchmark_summary(worktree_path: Path | None = None) -> dict:
    """tools/benchmark/run_benchmark.pyをサブプロセスとして実行し、終了コードと直近の
    メトリクスレポート(取得できれば)を返す。

    tools/benchmark/fixtures配下の固定シナリオによる一般的な安全性の健全性チェックに
    加えて、worktree_pathを指定した場合は`--target-worktree`経由で、実際にエスカレー
    ション対象ファイルが属するworktree内のPytestスイートもDockerサンドボックス内で
    追加実行する(instructions/126、report["target_specific_pytest"]に格納される)。
    Docker未導入の環境ではPre-flight Checkでhard failし(exit code 1、
    instructions/119で実装済み)、その結果もそのまま誠実に記録する。
    """
    cmd = ["uv", "run", "python", "tools/benchmark/run_benchmark.py"]
    if worktree_path is not None:
        cmd += ["--target-worktree", str(worktree_path)]
    result = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    reports = sorted(BENCHMARK_REPORTS_DIR.glob("benchmark_*.json"))
    report = None
    if reports:
        try:
            report = json.loads(reports[-1].read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            report = None
    return {
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
        "report": report,
    }


def _render_target_specific_pytest_section(report: dict) -> str:
    """report["target_specific_pytest"](instructions/126、run_benchmark.pyが
    --target-worktree指定時に追加実行する、エスカレーション対象ファイル固有の
    Pytest結果)をMarkdownのアノテーションセクションへ整形する。

    worktree_pathが未指定だった等で結果自体が存在しない場合は空文字を返す
    (PRドラフトに空セクションを残さない)。
    """
    target_result = report.get("target_specific_pytest")
    if not target_result:
        return ""

    returncode = target_result.get("returncode")
    if returncode is None:
        status = f"⚠️ 実行不可: {target_result.get('error', '(不明なエラー)')}"
    elif returncode == 0:
        status = "✅ 全テスト成功(exit code 0)"
    else:
        status = f"❌ 失敗(exit code {returncode})"

    junit_results = target_result.get("junit_results") or {}
    passed = sum(1 for ok in junit_results.values() if ok)
    failed = sum(1 for ok in junit_results.values() if not ok)
    stderr_tail = (target_result.get("stderr_tail") or "")[-1000:]

    section = (
        "\n## 対象ファイル固有のPytest検証(instructions/126)\n"
        f"- 実行結果: {status}\n"
        f"- テスト件数: 成功 {passed}件 / 失敗 {failed}件(合計{len(junit_results)}件)\n"
    )
    if failed or returncode not in (0, None):
        section += f"- 標準エラー出力(末尾抜粋):\n```text\n{stderr_tail}\n```\n"
    return section


def _write_pr_draft(
    *,
    branch_name: str,
    worktree_path: Path,
    instruction: dict,
    benchmark_summary: dict,
    state: AuditState,
) -> Path:
    """人間レビュー用のPRドラフト(Markdown)を生成する。"""
    PR_DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    draft_path = PR_DRAFT_DIR / f"pr_draft_{now.strftime('%Y%m%d_%H%M%S')}.md"

    benchmark_status = (
        "✅ 完了(exit code 0)"
        if benchmark_summary["returncode"] == 0
        else f"⚠️ exit code {benchmark_summary['returncode']}"
    )
    report = benchmark_summary.get("report") or {}
    aggregate = report.get("aggregate", report.get("status", "(レポート取得不可)"))
    target_specific_section = _render_target_specific_pytest_section(report)

    body = (
        "# 🚨 CTOエスカレーション PRドラフト\n\n"
        "## エスカレーション理由\n"
        f"- 対象ファイル: `{state['file_path']}`\n"
        f"- Qwenの診断: {state.get('diagnosis', '(なし)')}\n"
        f"- Qwenの自己評価付き修正案(原文):\n```json\n{_strip_code_fence(state.get('raw_json_text', ''))}\n```\n\n"
        f"## CTO(Claude, {CTO_MODEL})による修正案\n"
        f"- target_name: `{instruction['target_name']}`\n"
        f"- triage_type: `{instruction['triage_type']}`\n\n"
        f"```python\n{instruction['new_code']}\n```\n\n"
        "## 隔離ブランチでのサンドボックス検証\n"
        f"- ブランチ: `{branch_name}`\n"
        f"- 検証用worktree(`{worktree_path}`)はこの検証完了後に自動的に破棄済みです"
        "(ブランチ自体は破棄せず保持しています)。\n"
        f"- ベンチマークハーネス(tools/benchmark/run_benchmark.py)の実行結果: {benchmark_status}\n"
        "  - ※この検証は既存のDockerサンドボックスハーネス(固定fixture)による一般的な"
        "安全性チェックであり、今回の修正対象ファイル固有のテストではありません。\n"
        f"  - 集計結果: `{json.dumps(aggregate, ensure_ascii=False)}`\n"
        f"{target_specific_section}\n"
        "## レビュー・マージ手順(人間向け)\n"
        f"1. `git worktree add <任意の作業ディレクトリ> {branch_name}` "
        "(または `git checkout` でも可)でブランチを復元し、実際の差分・挙動を確認する。\n"
        f"2. 問題なければ通常のPRフローでこのブランチ(`{branch_name}`)をレビュー・マージする。\n"
        f"3. 不要と判断した場合は `git branch -D {branch_name}` で後片付けする。\n\n"
        "---\n"
        "⏸️ このプロセスはここで安全に一時停止(Suspend)しています。以後の自動適用・"
        "マージは行いません。人間によるレビューが必要です。\n"
    )
    draft_path.write_text(body, encoding="utf-8")
    return draft_path


def _record_successful_escalation_experience(
    *, branch_name: str, pr_draft_path: Path, instruction: dict, state: AuditState
) -> None:
    """CTOエスカレーション経由の修正が実際にベンチマークへ通過した「成功体験」を
    ai_knowledge_base.jsonへフィードバックする(instructions/159: 経験再生アーキテクチャ
    のループ完結)。sandbox_verify_nodeからベンチマーク通過(returncode == 0)を確認した
    直後にのみ呼び出す(失敗した修正案を将来の検索対象として汚染しないため)。
    """
    context_text = (
        f"{state.get('diagnosis', '')} {state.get('error_log', '')} "
        f"{instruction.get('target_name', '')} {instruction.get('triage_type', '')}"
    )
    entry = {
        "id": f"runtime-{branch_name}",
        "summary": (
            f"[CTOエスカレーション成功] '{instruction.get('target_name')}' "
            f"({state.get('file_path', '')})の修正がベンチマークに通過した"
        )[:200],
        "keywords": extract_keywords(context_text),
        "filepath": str(pr_draft_path.relative_to(BASE_DIR)).replace("\\", "/"),
    }
    record_experience(entry)


def sandbox_verify_node(state: AuditState) -> dict:
    """【隔離ブランチでのサンドボックス検証】CTOの修正案を、メインの作業ディレクトリを
    一切汚さない git worktree 上の専用ブランチへ適用・コミットし、既存のDockerサンドボックス
    ベンチマークハーネスを実行した上で、人間レビュー用のPRドラフトを生成する。

    このノードに到達するのはcto_instructionが設定されている場合のみ(_route_after_cto)。
    worktree自体は managed_git_worktree により処理の成功・失敗に関わらず必ず破棄される
    (使い捨て)。人間レビューのために残るのはGitブランチのみ。
    """
    instruction = state["cto_instruction"]
    repo_root = _find_git_repo_root(state["file_path"])
    branch_name: str | None = None

    try:
        with managed_git_worktree(repo_root) as (worktree_path, branch_name):
            target_abs_path = Path(instruction["file_path"]).resolve()
            relative_path = target_abs_path.relative_to(repo_root.resolve())
            instruction_in_worktree = dict(instruction)
            instruction_in_worktree["file_path"] = str(worktree_path / relative_path)

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8", errors="strict"
            ) as f:
                json.dump(instruction_in_worktree, f, ensure_ascii=False, indent=2)
                instruction_json_path = f.name

            try:
                apply_result = subprocess.run(
                    [
                        "uv",
                        "run",
                        "python",
                        str(BASE_DIR / "tools" / "ast_modifier.py"),
                        instruction_json_path,
                    ],
                    cwd=str(BASE_DIR),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="strict",
                )
            finally:
                Path(instruction_json_path).unlink(missing_ok=True)

            if apply_result.returncode != 0:
                message = (
                    "🚨 [サンドボックス検証失敗] CTOの修正案の適用(ast_modifier.py)に"
                    f"失敗しました: {(apply_result.stdout + apply_result.stderr).strip()}"
                )
                return {
                    "result_message": message,
                    "escalation_branch": branch_name,
                    "audit_history": [f"[サンドボックス検証] {message}"],
                }

            subprocess.run(
                ["git", "add", "--", str(relative_path)], cwd=str(worktree_path), check=True
            )
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    f"fix: CTOエスカレーションによる自動修正 ({branch_name})",
                ],
                cwd=str(worktree_path),
                check=True,
            )

            benchmark_summary = _run_benchmark_summary(worktree_path)
            pr_draft_path = _write_pr_draft(
                branch_name=branch_name,
                worktree_path=worktree_path,
                instruction=instruction,
                benchmark_summary=benchmark_summary,
                state=state,
            )

            if benchmark_summary.get("returncode") == 0:
                # 【instructions/159】「ベンチマークを通過した」という成功体験のみを
                # 次回以降のCTOエスカレーション時に検索可能な経験として記録する。
                _record_successful_escalation_experience(
                    branch_name=branch_name,
                    pr_draft_path=pr_draft_path,
                    instruction=instruction,
                    state=state,
                )

            message = (
                f"🧑‍💼 [CTOエスカレーション完了] 隔離ブランチ '{branch_name}' へ"
                "修正案を適用・コミットしました(検証用worktreeは既に破棄済みです)。\n"
                f"📄 PRドラフトを生成しました -> {pr_draft_path}\n"
                "⏸️ 安全のため、このファイルへの自動適用処理を一時停止(Suspend)します。"
                "人間によるレビュー・マージが必要です。"
            )
            return {
                "result_message": message,
                "escalation_branch": branch_name,
                "pr_draft_path": str(pr_draft_path),
                "audit_history": [f"[サンドボックス検証] {message}"],
            }
    except Exception as e:  # noqa: BLE001 - 予期しない失敗も安全に一時停止させる
        message = f"🚨 [サンドボックス検証失敗] 予期しないエラー: {e}"
        result: dict = {
            "result_message": message,
            "audit_history": [f"[サンドボックス検証] {message}"],
        }
        if branch_name is not None:
            result["escalation_branch"] = branch_name
        return result


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
    if state.get("cto_escalated"):
        summary_lines.append("🧑‍💼 CTO(Claude)への内容面エスカレーションが発生しました。")
        if state.get("escalation_branch"):
            summary_lines.append(f"隔離ブランチ: {state.get('escalation_branch', '')}")
        if state.get("pr_draft_path"):
            summary_lines.append(f"PRドラフト: {state.get('pr_draft_path', '')}")
        if state.get("dead_letter_path"):
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
    graph.add_node("cto_node", cto_node)
    graph.add_node("sandbox_verify", sandbox_verify_node)
    graph.add_node("gemma_fallback", gemma_fallback_node)
    graph.add_node("reporter", reporter_node)

    graph.set_entry_point("supervisor")
    graph.add_edge("supervisor", "craftsman")
    graph.add_edge("craftsman", "validate")
    # 検証成功かつQwenが内容面で不確実性を申告していなければ適用へ、検証成功だが
    # 不確実性が高ければCTOエスカレーションへ、検証失敗かつリトライ余地があれば
    # 職人ノードへ差し戻し、リトライを使い果たしたらサーキットブレーカーが作動して
    # Gemmaフォールバックへ(こちらは形式面のみのエスカレーションで、CTO経路とは独立)。
    graph.add_conditional_edges(
        "validate",
        _route_after_validate,
        {
            "apply": "apply",
            "craftsman": "craftsman",
            "gemma_fallback": "gemma_fallback",
            "cto_node": "cto_node",
        },
    )
    # CTOが有効な修正案を取得できた場合のみ隔離ブランチでのサンドボックス検証へ進み、
    # 失敗した場合(デッドレター済み)は直接reporterへ進んで安全に一時停止する。
    graph.add_conditional_edges(
        "cto_node",
        _route_after_cto,
        {"sandbox_verify": "sandbox_verify", "reporter": "reporter"},
    )
    graph.add_edge("apply", "reporter")
    graph.add_edge("sandbox_verify", "reporter")
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
        "requires_cto_escalation": False,
        "cto_instruction": {},
        "cto_escalated": False,
        "pr_draft_path": "",
        "escalation_branch": "",
    }
    return app.invoke(initial_state)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python tools/agent_graph.py <target_file>")
        sys.exit(1)
    run_self_repair(sys.argv[1])

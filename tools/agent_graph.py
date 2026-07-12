"""
tools/agent_graph.py
======================
Nazo-Agent: LangGraphによる自律修復ループ(Feature 1.x)。

Aiderへの非決定的な依存を廃止し、ローカルLLM(Ollama)による
「スキャン→レビュー→編集→(ループ)→報告」の全履歴保持型・最大3回ループの
自己修復エージェントを構築する。各ノードの発見・判断・編集内容は
audit_history に蓄積され、後続ノード/次ループの判断材料として保持される。

対象モデル: gemma4:12b (Ollamaへpull済み。ハイフンなしのタグ表記が正)。
"""

import operator
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from tools.ast_modifier import _atomic_write_text
from tools.pyright_tool import get_type_info as _pyright_get_type_info

MAX_REVISIONS = 3
OLLAMA_MODEL = "gemma4:12b"

llm = ChatOllama(model=OLLAMA_MODEL, temperature=0.1)


@tool
def get_type_info(file_path: str) -> str:
    """指定ファイルをPyrightで型検査し、実際の型エラー・型不整合の診断結果を返す。
    型エラーを推測で修正案に組み込まず、必ずこのツールで実診断を取得してから判断すること。
    """
    return _pyright_get_type_info(file_path)


# Editor(コード修正)ノードのみ、型情報クエリのためこのツールをbindする。
editor_llm_with_tools = llm.bind_tools([get_type_info])


class AuditState(TypedDict):
    file_path: str
    original_code: str
    current_code: str
    audit_history: Annotated[list[str], operator.add]
    revision_count: int
    status: str
    messages: Annotated[list[BaseMessage], add_messages]


def _extract_text(response) -> str:
    """ChatOllamaの応答(AIMessage等)からテキスト本文を取り出す。"""
    content = getattr(response, "content", response)
    return content if isinstance(content, str) else str(content)


def scanner_node(state: AuditState) -> dict:
    """current_code を読み、問題箇所の抽出のみを行う(修正はしない)。"""
    prompt = (
        "あなたはコードレビュアーです。以下のPythonコードを読み、"
        "問題点(バグ・型不整合・未使用インポート・悪い命名等)を箇条書きで列挙してください。"
        "修正コードは書かず、問題点の指摘のみに専念してください。"
        "問題が無ければ「問題なし」と答えてください。\n\n"
        f"```python\n{state['current_code']}\n```"
    )
    findings = _extract_text(llm.invoke(prompt))
    return {"audit_history": [f"[Scanner] {findings}"]}


def reviewer_node(state: AuditState) -> dict:
    """scanner の指摘を踏まえ、CLEAN か NEEDS_FIX かを判定する。"""
    history_text = "\n".join(state["audit_history"])
    prompt = (
        "あなたは監査責任者です。以下のレビュー履歴を踏まえ、このコードが"
        "修正不要(CLEAN)か、修正が必要(NEEDS_FIX)かを判定してください。"
        "回答は必ず `CLEAN` または `NEEDS_FIX` の1単語のみで答えてください。\n\n"
        f"【レビュー履歴】\n{history_text}"
    )
    verdict_text = _extract_text(llm.invoke(prompt)).strip().upper()
    status = "CLEAN" if "CLEAN" in verdict_text and "NEEDS_FIX" not in verdict_text else "NEEDS_FIX"
    return {
        "status": status,
        "audit_history": [f"[Reviewer] 判定: {status}"],
    }


def editor_llm_node(state: AuditState) -> dict:
    """NEEDS_FIXの修正案をLLMに構築させる(1手)。

    get_type_info ツールが呼ばれた場合は tool_calls を含む応答を返し、
    ToolNode 経由で実診断結果を messages へ積んでから再度このノードへ差し戻す
    (Conditional Edge)。型情報を確認せず推測で修正するハルシネーションを防ぐ。
    最終的にtool_callsを含まない応答が返った時点で、その内容が最終修正案となる。
    """
    existing_messages = state.get("messages") or []

    # 直前がToolMessage(=ツール実行結果が積まれた直後)ならプロンプトは追加せず、
    # 既存の履歴のままLLMを再呼出しして続きの推論をさせる。
    if existing_messages and isinstance(existing_messages[-1], ToolMessage):
        response = editor_llm_with_tools.invoke(existing_messages)
        return {"messages": [response]}

    history_text = "\n".join(state["audit_history"])
    prompt = (
        "あなたはシニアエンジニアです。以下のレビュー履歴で指摘された問題を"
        "すべて修正した、完全なソースコードを出力してください。"
        "型エラー・型不整合が疑われる場合は、推測で修正せず、必ず get_type_info ツールで"
        f"実際の型診断を取得してから判断してください(file_path には '{state['file_path']}' を渡すこと)。"
        "調査が完了したら、説明文やMarkdownのコードフェンスは一切付けず、"
        "ファイルの内容そのものだけを最終回答として出力してください。\n\n"
        f"【レビュー履歴】\n{history_text}\n\n"
        f"【現在のコード】\n{state['current_code']}"
    )
    new_messages = existing_messages + [HumanMessage(content=prompt)]
    response = editor_llm_with_tools.invoke(new_messages)
    return {"messages": [HumanMessage(content=prompt), response]}


def _editor_has_tool_calls(state: AuditState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return "finalize_edit"


def finalize_edit_node(state: AuditState) -> dict:
    """tool_callsを含まない最終応答から完全なソースコードを抽出し current_code を上書きする。"""
    new_code = _extract_text(state["messages"][-1]).strip()

    # LLMがMarkdownのコードフェンスを付けてきた場合の安全策として除去する。
    if new_code.startswith("```"):
        lines = new_code.split("\n")
        lines = lines[1:] if lines and lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        new_code = "\n".join(lines)

    next_revision = state["revision_count"] + 1
    return {
        "current_code": new_code,
        "revision_count": next_revision,
        "audit_history": [f"[Editor] 修正を適用しました (revision {next_revision})"],
    }


def reporter_node(state: AuditState) -> dict:
    """最終サマリーを出力し、current_code をファイルへ一括書き戻す。"""
    summary_lines = [
        "=== Nazo-Agent 自律修復ループ 完了報告 ===",
        f"対象ファイル: {state['file_path']}",
        f"最終ステータス: {state['status']}",
        f"修正回数: {state['revision_count']}",
        "--- 履歴 ---",
        *state["audit_history"],
    ]
    summary = "\n".join(summary_lines)
    print(summary)

    if state["current_code"] != state["original_code"]:
        _atomic_write_text(Path(state["file_path"]), state["current_code"])

    return {"audit_history": [f"[Reporter] {summary}"]}


def _route_after_review(state: AuditState) -> str:
    if state["status"] == "CLEAN" or state["revision_count"] >= MAX_REVISIONS:
        return "reporter"
    return "editor"


def build_graph():
    graph = StateGraph(AuditState)
    graph.add_node("scanner", scanner_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("editor", editor_llm_node)
    graph.add_node("tools", ToolNode([get_type_info]))
    graph.add_node("finalize_edit", finalize_edit_node)
    graph.add_node("reporter", reporter_node)

    graph.set_entry_point("scanner")
    graph.add_edge("scanner", "reviewer")
    graph.add_conditional_edges(
        "reviewer", _route_after_review, {"reporter": "reporter", "editor": "editor"}
    )
    # Editor: get_type_info の tool_calls が返った場合は ToolNode へ、
    # 型情報を確認した(または不要と判断した)最終応答が返ったら finalize_edit へ。
    graph.add_conditional_edges(
        "editor", _editor_has_tool_calls, {"tools": "tools", "finalize_edit": "finalize_edit"}
    )
    graph.add_edge("tools", "editor")
    graph.add_edge("finalize_edit", "scanner")
    graph.add_edge("reporter", END)

    return graph.compile()


def run_self_repair(file_path: str) -> dict:
    """指定ファイルに対し、自律修復ループ(スキャン→レビュー→編集、最大3回)を実行する。"""
    path = Path(file_path)
    source = path.read_text(encoding="utf-8")

    app = build_graph()
    initial_state: AuditState = {
        "file_path": str(path),
        "original_code": source,
        "current_code": source,
        "audit_history": [],
        "revision_count": 0,
        "status": "UNKNOWN",
        "messages": [],
    }
    return app.invoke(initial_state)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python tools/agent_graph.py <target_file>")
        sys.exit(1)
    run_self_repair(sys.argv[1])

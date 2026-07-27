"""
tools/generate_doc_via_gemini.py
==================================
docs/architecture_facts.json（決定論的に抽出済みのファクトのみ）をコンテキストとして
Gemini API へ送信し、プレーンテキストのシステム概要文書 docs/system_overview_v2.md を
生成するツール(instructions/251)。

【Read-Only原則】本スクリプトはソースコード(apps/等)を一切読み込まない。入力は
docs/architecture_facts.json のみであり、文章表現はGemini自身の推論に委ねるが、
その推論の材料となる事実はStep1(tools/extract_architecture.py)でAST抽出済みの
ものに限定する(ファクトデータに存在しない情報を捏造させない)。

【モデル指定】instructions/251で明示された "gemini-3.1-pro-preview" を無断で
差し替えない。APIがこのモデル名を受理しない場合は、フォールバックせずエラーを
そのまま送出して停止する(呼び出し元が正しいモデル名を確認して再実行する)。

使い方:
    python tools/generate_doc_via_gemini.py
    (事前に環境変数 GEMINI_API_KEY の設定、またはリポジトリルートの.envへの
     記載が必要)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai.types import GenerateContentConfig

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
FACTS_PATH = REPO_ROOT / "docs" / "architecture_facts.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "system_overview_v2.md"
TMP_PATH = REPO_ROOT / "docs" / "system_overview_v2.tmp.md"

# instructions/251 で明示されたモデル名。無断で差し替えない(§モジュールdocstring参照)。
MODEL_NAME = "gemini-3.1-pro-preview"

# tools/nazo_agent.py と同じ規約(リポジトリルートの.envを読む)。ファイルが存在しない
# 環境では無害にno-opし、OSレベルの環境変数がそのまま使われる。
load_dotenv(REPO_ROOT / ".env")

PROMPT_TEMPLATE = """あなたはシステムアーキテクチャドキュメントの専門家です。以下は、対象システムの
コードベースをPythonのastモジュールのみで機械的に抽出した「決定論的なファクトデータ」
(JSON)です。推論や憶測による事実の捏造は一切行われていません。

このファクトデータのみを根拠として、日本語のシステム概要ドキュメントを作成してください。
ファクトデータに存在しない情報を推測で補ってはいけませんが、ファクトから合理的に読み取れる
「フォルダ・ファイル構成、関数名、エンドポイントが何を意味し、どう関係しているか」の
説明・要約は積極的に行ってください。

出力は以下の4つのセクションを、この順序・見出しでMarkdown形式にて必ず含めてください:

## 1. アプリの構成と関係性
フォルダとファイルの構成(filesの各pathとclasses/functions)、および抽出した
関数・クラス・変数等がどのような意味と関係性を持つのかを説明してください。

## 2. ページ動作とUX
frontend_pagesに列挙された各ページの動作原理と、ユーザーのアクションに基づく
リアクション（処理フロー）を説明してください。

## 3. 管理者コンソール（権限と操作）
管理者が扱う領域（api_routesおよびrouter_mountsのうち /api/admin 配下の
エンドポイント等）において、何を管理（確認・決定・修正）し、管理者のアクションが
システムにどのような変化を与えるのかを説明してください。

## 4. データフロー
ユーザー・管理者・AIが生成したデータが、フロントエンド、バックエンド、ワーカー、
DB（SQLite/Firestore）をどのように流れるのかの全体図を説明してください。

出力はプレーンテキスト(Markdown)のみとし、上記4セクション以外の前置き・後書き・
断り書きは付けないでください。

【ファクトデータ(JSON)】
{facts_json}
"""


def load_facts() -> dict:
    """docs/architecture_facts.jsonを読み込む(Step1の出力。存在しない場合はまず
    tools/extract_architecture.pyを実行する必要がある)。
    """
    if not FACTS_PATH.exists():
        raise FileNotFoundError(
            f"{FACTS_PATH} が見つかりません。先に `python tools/extract_architecture.py` "
            "を実行してファクトデータを生成してください。"
        )
    with open(FACTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _require_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise EnvironmentError("GEMINI_API_KEYが未設定です。")
    return key


def build_prompt(facts: dict) -> str:
    """ファクトデータをコンパクトなJSON(インデントなし)に直列化してプロンプトへ埋め込む
    (350KB超のpretty-printは情報量を増やさずトークンを浪費するため)。
    """
    facts_json = json.dumps(facts, ensure_ascii=False)
    return PROMPT_TEMPLATE.format(facts_json=facts_json)


def call_gemini(prompt: str, api_key: str) -> str:
    """Gemini APIへプロンプトを送信し、生成されたプレーンテキストを返す。
    構造化出力(response_schema)は使わない(自由記述のMarkdown文章を求めているため)。
    """
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=GenerateContentConfig(temperature=0.3),
    )
    if not response.text:
        raise RuntimeError("Gemini APIから空の応答が返されました。")
    return response.text


def _atomic_write_text(text: str, tmp_path: Path, final_path: Path) -> None:
    """一時ファイルへ書き込み+os.fsyncでディスクへの書き込みを確実にした直後、
    os.replaceで目的のファイルへ不可分にすげ替える(tools/extract_architecture.py.
    _atomic_write_jsonと同じ設計思想)。
    """
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, final_path)


def main() -> int:
    facts = load_facts()
    try:
        api_key = _require_api_key()
        prompt = build_prompt(facts)
        doc_text = call_gemini(prompt, api_key)
    except Exception as e:
        print(f"🚨 ドキュメント生成に失敗しました: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    _atomic_write_text(doc_text, TMP_PATH, OUTPUT_PATH)
    print(f"✅ システム概要ドキュメントを書き出しました: {OUTPUT_PATH}")
    print(f"   モデル: {MODEL_NAME} / 出力文字数: {len(doc_text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

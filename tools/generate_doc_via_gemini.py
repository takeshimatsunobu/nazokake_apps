"""
tools/generate_doc_via_gemini.py
==================================
docs/architecture_facts.json（決定論的に抽出済みのファクトのみ）をコンテキストとして
Gemini API へ送信し、プレーンテキストのシステム概要文書 docs/system_overview_v3.md を
生成するツール(instructions/251, instructions/254で詳細化)。

【Read-Only原則】本スクリプトはソースコード(apps/等)を一切読み込まない。入力は
docs/architecture_facts.json のみであり、文章表現はGemini自身の推論に委ねるが、
その推論の材料となる事実はStep1(tools/extract_architecture.py)でAST抽出済みの
ものに限定する(ファクトデータに存在しない情報を捏造させない)。

【モデル指定】instructions/251で明示された "gemini-3.1-pro-preview" を無断で
差し替えない。APIがこのモデル名を受理しない場合は、フォールバックせずエラーを
そのまま送出して停止する(呼び出し元が正しいモデル名を確認して再実行する)。

【instructions/254: 要約癖の封じ込め(instructions/255で撤回・方針転換)】初版
(docs/system_overview_v2.md)が抽象的すぎたため、一度は「全件を省略なく列挙する」
プロンプトへ変更したが、出力トークン上限を超過し、かつAPI呼び出しに明示的な
タイムアウトが無かったためプロセスがハングする結果となった(instructions/255で
観測・報告)。そのため「全変数・全関数の逐一列挙」は撤回し、「データフローと
コールチェーンの追跡」に特化した簡潔な構造化出力へ方針転換している。

【instructions/255: 防弾化(Fail-Closed)】Gemini API呼び出しにHttpOptions経由で
明示的なタイムアウトを設定し、無限待機を許容しない(タイムアウト時は例外を
そのまま送出してmain()が即座に失敗する)。なお本スクリプトの
_atomic_write_textはfilelock等の排他制御を一切使用しない単純な
tmp+fsync+os.replaceのみのため、排他制御のタイムアウトという概念自体が
該当しない(単一プロセスの逐次実行を前提とした設計であり、複数プロセスからの
同時書き込みは想定していない)。

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
from google.genai.types import GenerateContentConfig, HttpOptions

if sys.platform == "win32":
    # typeshedのsys.stdout/stderrはTextIOとして型付けされreconfigure()を
    # 宣言していないが、実行時は実際にTextIOWrapperであり存在する。
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    sys.stderr.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

REPO_ROOT = Path(__file__).resolve().parent.parent
FACTS_PATH = REPO_ROOT / "docs" / "architecture_facts.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "system_overview_v3.md"
TMP_PATH = REPO_ROOT / "docs" / "system_overview_v3.tmp.md"

# instructions/251 で明示されたモデル名。無断で差し替えない(§モジュールdocstring参照)。
MODEL_NAME = "gemini-3.1-pro-preview"

# instructions/255: Fail-Closed。無限待機を許容せず、超過時は例外をそのまま送出して
# 停止する(ミリ秒指定。google.genai.types.HttpOptions.timeoutの単位)。
API_TIMEOUT_MS = 180_000

# tools/nazo_agent.py と同じ規約(リポジトリルートの.envを読む)。ファイルが存在しない
# 環境では無害にno-opし、OSレベルの環境変数がそのまま使われる。
load_dotenv(REPO_ROOT / ".env")

PROMPT_TEMPLATE = """あなたはシステムアーキテクチャドキュメントの専門家です。以下は、対象システムの
コードベースをPythonのastモジュールのみで機械的に抽出した「決定論的なファクトデータ」
(JSON)です。推論や憶測による事実の捏造は一切行われていません。

このファクトデータのみを根拠として、日本語のシステム概要ドキュメントを作成してください。
ファクトデータに存在しない情報を推測で補ってはいけません。

【出力構造の絶対厳守: 出力トークン上限による欠損防止】
本ドキュメントの目的は「全変数・全関数の逐一列挙」ではなく、「データフローと
コールチェーンの正確な追跡」です。Markdownの見出し階層を厳格に守ってください
(## はセクション見出し、### は各ページ/エンドポイント/機能単位の小見出し)。
各項目は要点を絞って簡潔に記述し、出力が途中で打ち切られることを絶対に避けて
ください(冗長な説明よりも、完結した構造化出力を優先すること)。

出力は以下の4つのセクションを、この順序・見出しでMarkdown形式にて必ず含めてください:

## 1. アプリの構成と関係性
filesの主要なディレクトリ(apps/, tools/, packages/, infra/)ごとに、その役割と
主要なモジュール・クラスがどう連携しているかを簡潔に説明してください(個々の
関数を逐一列挙する必要はなく、構造と主要な依存関係の把握を目的とします)。

## 2. ページ動作とUX
frontend_pagesに列挙された各ページについて、###見出しでページごとに区切り、
以下の処理チェーンを関数名を明記して具体的に記述してください:
「ユーザーのアクション → 呼び出されるAPIパス(api_routesのpath/method) →
実行されるバックエンド関数(function) → ワーカーへの伝達(該当する場合) →
データベース(SQLite/Firestore)のどのテーブル/コレクションへの副作用か」。

## 3. 管理者コンソール（権限と操作）
api_routesおよびrouter_mountsのうち /api/admin 配下を含む管理者向け機能について、
###見出しで機能ごとに区切り、その機能がバックエンドのどの関数を呼び出し、DBの
状態をどう変更するか（何を確認・決定・修正できるか）を具体的に記述してください。

## 4. データフロー
ユーザー・管理者・AIが生成したデータが、UI→バックエンド→ワーカー→DB
(SQLite/Firestore)へと流れる代表的な経路を、簡潔に追跡してまとめてください。

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
    instructions/255: Fail-Closed。HttpOptions.timeoutで明示的なタイムアウトを
    設定し、API呼び出しが無限に待機することを許容しない(超過時はSDKが例外を
    送出し、main()側でそのまま失敗として扱う)。
    """
    client = genai.Client(api_key=api_key, http_options=HttpOptions(timeout=API_TIMEOUT_MS))
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=GenerateContentConfig(temperature=0.3, max_output_tokens=16384),
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

"""
tools/compile_knowledge.py
=============================
過去の指示書(tools/instructions/配下)を構造化エピソード記憶としてコンパイルする、
スタンドアロンのビルドスクリプト(Dynamic Experience Replay)。

tools/knowledge_retriever.py の軽量ローカル検索はこのスクリプトが事前生成する
run/ai_knowledge_base.json に対してのみ動作し、実行時にtools/instructions/を
再スキャンしない(推論時に大量のテキストファイルを毎回読み直すコストを避ける)。
指示書が追加・変更された場合は、このスクリプトを再実行してai_knowledge_base.json
を再ビルドすること。

使い方:
    uv run python tools/compile_knowledge.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# 【フェーズ2の構造整理で移設】tools/instructions/ は本番デプロイに不要な履歴文書として
# archive/instructions_history/tools_instructions/ へ隔離した(tools/check_instructions_
# layout.pyと同じ追従修正)。放置するとINSTRUCTIONS_DIRが空ディレクトリを指し続け、
# ai_knowledge_base.jsonが空のナレッジベースとしてサイレントに再生成されてしまう。
INSTRUCTIONS_DIR = BASE_DIR / "archive" / "instructions_history" / "tools_instructions"
KNOWLEDGE_BASE_PATH = BASE_DIR / "run" / "ai_knowledge_base.json"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ASCII識別子(関数名/ファイルパス/エラーコード等)と、日本語の漢字・カタカナの連続
# (複合名詞の簡易近似)の両方をキーワード候補として抽出する。形態素解析器(MeCab等)
# への依存を避けるための正規表現ベースの軽量抽出であり、判別力の低い語(「実装」等の
# 頻出語)の重み付けはtools/knowledge_retriever.py側のTF-IDFに委ねる(ここでは
# 過剰抽出を許容する)。
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_./\-]{2,}")
_JAPANESE_TOKEN_RE = re.compile(r"[一-鿿゠-ヿ]{2,}")
# HTTP/exit code等の裸の数値(例: "125"、"404")もエラーコードのキーワードとして
# 抽出する(識別子用の_ASCII_TOKEN_REは先頭に英字を要求するため数値のみは拾えない)。
_NUMERIC_TOKEN_RE = re.compile(r"\b\d{2,4}\b")
_ID_FROM_FILENAME_RE = re.compile(r"^(\d+)")
_MAX_KEYWORDS = 30
_MAX_SUMMARY_CHARS = 200


def _extract_id(filepath: Path) -> str:
    """ファイル名先頭の連番(例: "141_claude_....txt" -> "141")をIDとする。
    連番が見つからない場合はファイル名(拡張子抜き)そのものをIDとする。
    """
    match = _ID_FROM_FILENAME_RE.match(filepath.stem)
    return match.group(1) if match else filepath.stem


def _extract_summary(text: str) -> str:
    """先頭の空でない行(通常は【ミッション: ...】の行)を概要として採用する。"""
    for line in text.splitlines():
        stripped = line.strip().strip("【】")
        if stripped:
            return stripped[:_MAX_SUMMARY_CHARS]
    return ""


def extract_keywords(text: str) -> list[str]:
    """本文中のASCII識別子と日本語の漢字・カタカナ連続を抽出し、出現頻度が高い
    上位_MAX_KEYWORDS件を返す(重複は除去済み)。
    """
    tokens = (
        _ASCII_TOKEN_RE.findall(text)
        + _JAPANESE_TOKEN_RE.findall(text)
        + _NUMERIC_TOKEN_RE.findall(text)
    )
    counts = Counter(tokens)
    return [token for token, _ in counts.most_common(_MAX_KEYWORDS)]


def compile_knowledge_base() -> list[dict]:
    """tools/instructions/配下の全テキストファイル(再帰的に走査)を構造化エントリへ
    変換する。旧セッションの経緯で tools/instructions/tools/instructions/ という
    二重ネストが生じているファイルも rglob により同様に取り込む。
    """
    entries = []
    for filepath in sorted(INSTRUCTIONS_DIR.rglob("*.txt")):
        text = filepath.read_text(encoding="utf-8", errors="replace")
        entries.append(
            {
                "id": _extract_id(filepath),
                "summary": _extract_summary(text),
                "keywords": extract_keywords(text),
                "filepath": str(filepath.relative_to(BASE_DIR)).replace("\\", "/"),
            }
        )
    return entries


def main() -> int:
    entries = compile_knowledge_base()
    KNOWLEDGE_BASE_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✅ {len(entries)}件の指示書を構造化し、{KNOWLEDGE_BASE_PATH} へ書き出しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

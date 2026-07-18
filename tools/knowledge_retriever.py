"""
tools/knowledge_retriever.py
===============================
tools/compile_knowledge.py が事前生成した tools/ai_knowledge_base.json に対する、
軽量なローカル検索器(Dynamic Experience Replay)。

tools/agent_graph.py の cto_node がClaudeへエスカレーションする際、過去の指示書
すべてをプロンプトに詰め込む(コスト・コンテキスト汚染の両面で厳禁)のではなく、
現在のエラーログ・診断文と関連性の高い上位top_k件のみを動的に検索・注入するために
使う。VRAMを消費するEmbeddingモデルは使わず、各エントリのキーワード集合の有無のみ
を特徴量とする二値TF-IDF(IDF重み付き)とコサイン類似度による、Python標準ライブラリ
のみでの軽量実装。
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tools.compile_knowledge import KNOWLEDGE_BASE_PATH, extract_keywords  # noqa: E402


def _load_knowledge_base() -> list[dict]:
    """tools/ai_knowledge_base.jsonを読み込む。存在しない場合は空リストを返す
    (tools/compile_knowledge.pyを未実行の環境でもcto_nodeをクラッシュさせない)。
    """
    if not KNOWLEDGE_BASE_PATH.exists():
        return []
    return json.loads(KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8"))


def record_experience(entry: dict) -> None:
    """成功した修正の「経験」を新規エントリとしてai_knowledge_base.jsonへ追記する。

    tools/compile_knowledge.pyがtools/instructions/配下の指示書から事前コンパイルする
    静的なエントリ群とは異なり、これは実行時に生成される動的なエントリ(instructions/159:
    シャドウモード運用の要件「経験再生アーキテクチャのループ完結」)。呼び出し元
    (tools/agent_graph.py の sandbox_verify_node)がCTOエスカレーション経由の修正が
    ベンチマークに通過したことを確認した直後にのみ呼び出すことで、「ベンチマーク通過」
    という成功体験を次回以降のretrieve_experiences()から即座に検索可能にする
    (ループの完結)。

    entryは既存の静的エントリと同一スキーマ({"id", "summary", "keywords", "filepath"})
    を用いる。追記後は稼働ログとして標準出力へ記録内容を出力する(このフィードバックが
    実際に発生したことの客観的な証跡)。
    """
    entries = _load_knowledge_base()
    entries.append(entry)
    KNOWLEDGE_BASE_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        "📚 [Experience Replay] 成功体験をai_knowledge_base.jsonへ記録しました: "
        f"id={entry.get('id')!r} summary={entry.get('summary')!r} "
        f"keywords={entry.get('keywords')!r}"
    )


def _build_idf(entries: list[dict]) -> dict[str, float]:
    """全エントリにわたる各キーワードの逆文書頻度(IDF)を計算する。

    ほぼ全エントリに出現する語(「実装」「ファイル」等の一般語)ほど重みが下がり、
    少数のエントリだけに出現する特徴的な語(クラス名・エラーコード等の固有語)ほど
    重みが上がる。
    """
    n_docs = len(entries)
    if n_docs == 0:
        return {}
    doc_freq: Counter[str] = Counter()
    for entry in entries:
        for keyword in set(entry.get("keywords", [])):
            doc_freq[keyword] += 1
    return {
        keyword: math.log((n_docs + 1) / (freq + 1)) + 1.0
        for keyword, freq in doc_freq.items()
    }


def _cosine_similarity(
    query_keywords: set[str], entry_keywords: set[str], idf: dict[str, float]
) -> float:
    """2つのキーワード集合の、IDF重み付き二値ベクトル間のコサイン類似度。"""
    shared = query_keywords & entry_keywords
    if not shared:
        return 0.0
    numerator = sum(idf.get(k, 1.0) ** 2 for k in shared)
    query_norm = math.sqrt(sum(idf.get(k, 1.0) ** 2 for k in query_keywords))
    entry_norm = math.sqrt(sum(idf.get(k, 1.0) ** 2 for k in entry_keywords))
    if query_norm == 0 or entry_norm == 0:
        return 0.0
    return numerator / (query_norm * entry_norm)


def retrieve_experiences(query: str, top_k: int = 3) -> list[dict]:
    """queryと関連性の高い上位top_k件の過去の指示書エントリを、スコア降順で返す。

    知識ベース(tools/ai_knowledge_base.json)が存在しない、または空/該当なしの
    場合は空リストを返す(呼び出し元はRAG無しでの動作にフォールバックできる)。
    """
    entries = _load_knowledge_base()
    if not entries:
        return []

    idf = _build_idf(entries)
    query_keywords = set(extract_keywords(query))
    if not query_keywords:
        return []

    scored = []
    for entry in entries:
        entry_keywords = set(entry.get("keywords", []))
        score = _cosine_similarity(query_keywords, entry_keywords, idf)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored[:top_k]]

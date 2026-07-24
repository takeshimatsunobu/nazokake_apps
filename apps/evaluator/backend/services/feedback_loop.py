"""
feedback_loop.py
=================
Phase 4 Lv.1: ユーザーフィードバック(user_feedbacks)を起点に、Dynamic Few-Shotプールを
高評価データで強化するための土台。generation.py の既存生成フロー(generate_via_gemini /
generate_via_llmjp)は本モジュールを呼び出さない限り一切影響を受けない(オプトイン)。
"""

import asyncio

from nazokake_core.database import async_get_item

HIGH_RATING_THRESHOLD = 4


def _fetch_high_rated_doc_ids_sync(db, limit: int) -> list:
    """user_feedbacks から overall_score >= HIGH_RATING_THRESHOLD の doc_id を重複なく抽出する同期ヘルパー。"""
    query = (
        db.collection("user_feedbacks")
        .where("overall_score", ">=", HIGH_RATING_THRESHOLD)
        .limit(limit)
    )
    doc_ids = []
    seen = set()
    for doc in query.stream():
        doc_id = doc.to_dict().get("doc_id")
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            doc_ids.append(doc_id)
    return doc_ids


async def fetch_high_rated_nazokake_ids(db, limit: int = 200) -> list:
    """高評価(overall_score >= 4)を得た nazokake_items の doc_id リストを重複なく返す。"""
    return await asyncio.to_thread(_fetch_high_rated_doc_ids_sync, db, limit)


async def _fetch_fewshot_entry(doc_id: str):
    """指定doc_idのnazokake_items(ローカルDB)から、Few-shotプール互換のCoT辞書を
    組み立てる(取得できる範囲のみ)。

    toku/kokoro が欠落しているドキュメント(生成失敗等)はNoneを返しスキップ対象とする。
    """
    data = await async_get_item(doc_id)
    if data is None:
        return None
    result = data.get("result") or data.get("result_gemini") or {}
    toku = result.get("toku")
    kokoro = result.get("kokoro")
    if not toku or not kokoro:
        return None
    thinking = result.get("thinking") or {}
    return {
        "associations": thinking.get("associations", []),
        "kakekotoba": thinking.get("kakekotoba", []),
        "shared_essence": thinking.get("shared_essence", ""),
        "surprise_check": thinking.get("surprise_check", ""),
        "toku": toku,
        "kokoro": kokoro,
    }


async def build_high_rated_fewshot_entries(db, limit: int = 200) -> list:
    """ユーザー高評価のnazokake_itemsから、Few-shotプール互換の辞書リストを組み立てる(Lv.1の土台)。

    取得できたエントリのみを返す(欠損データはスキップ)。呼び出し側(generation.py)が
    このリストを既存の静的プールへどうマージ/差し替えるかを判断する。
    """
    doc_ids = await fetch_high_rated_nazokake_ids(db, limit)
    entries = []
    for doc_id in doc_ids:
        entry = await _fetch_fewshot_entry(doc_id)
        if entry:
            entries.append(entry)
    return entries

"""services/toku_kokoro.py
==========================
なぞかけの「解き(toku)」「そのこころ(kokoro)」を、nazokake_itemsの1行(dict)から
一貫した優先順位で取り出す共有ヘルパー(Phase5/6)。

result(またはresult_gemini)の構造化フィールドを優先し、それが無い場合のみ
nazokake_text(自由文)を正規表現でパースする。この正規表現は
frontend/public/ui/feed.js::renderFeedItem() のパースロジックと完全に一致させる
必要がある(表示側と一致しない基準で「差分あり/なし」を判定すると、ユーザーが
何も変更していないのに赤ペン修正として誤検知されるため)。
"""
from __future__ import annotations

import re
from typing import Any

_TOKU_PATTERN = re.compile(r"かけて、?「?(.*?)」?と[解と]く")
_KOKORO_PATTERN = re.compile(r"その[心こころ]は、?(.*)")


def extract_toku_kokoro(item: dict[str, Any]) -> tuple[str, str]:
    """item(nazokake_itemsの1行)から(toku, kokoro)を取り出す。取得できない場合は空文字。"""
    result = item.get("result") or item.get("result_gemini") or {}
    toku = str(result.get("toku") or "").strip()
    kokoro = str(result.get("kokoro") or "").strip()
    if not toku and not kokoro:
        text = item.get("nazokake_text") or ""
        toku_match = _TOKU_PATTERN.search(text)
        kokoro_match = _KOKORO_PATTERN.search(text)
        toku = toku_match.group(1) if toku_match else ""
        kokoro = kokoro_match.group(1) if kokoro_match else text
    return toku, kokoro


def build_nazokake_text(odai: str, toku: str, kokoro: str) -> str:
    """(odai, toku, kokoro)から、extract_toku_kokoro()が再度パースできる定型文を組み立てる。"""
    return f"「{odai}」とかけて、「{toku}」ととく。そのこころは、{kokoro}"

"""
nazokake_core/parser.py
=========================
LLM出力(特にELYZA等ローカル8Bクラスモデル)からなぞかけ生成結果を堅牢に抽出する
ユーティリティ。apps/evaluator/backend/services/output_parser.py にあった
_extract_json_dict 系ロジックを、apps/batch_factory (batch/llm_client.py) からも
再利用できるようこのパッケージへ統合した(personas.pyと同じSSoT化の方針)。

8Bクラスのローカルモデルは、キャラクター性の強いペルソナ指示とJSON-only制約が
競合すると、前置きの掛け声・舞台演出・入れ子の不正記法(`"x"="y"`、日本語鉤括弧
`「」`によるクオート等)を混ぜたテキストを返すことがある。json.loads単体では
即座に全体が失敗するため、以下の段階的フォールバックで可能な限り toku/kokoro を
救出する。
"""
from __future__ import annotations

import json
import re


def _first_json_block(text: str) -> str | None:
    """最初の '{' から対応する '}' までの最小完結ブロックを返す(文字列内の括弧は無視)。

    貪欲な r'\\{.*\\}' は「文章 {A} 文章 {B}」で{A}〜{B}全体を掴んでしまうため、
    波括弧の対応をスキャンして最初の1ブロックだけを正確に切り出す。閉じが無ければ
    残り全部を返す(途中で出力が切れたケースをサルベージ側へ委ねるため)。
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def _salvage_str_field(raw: str, key: str) -> str | None:
    """raw から "key": "..." / "key": 「...」 の文字列値を1つだけ取り出す(堅牢サルベージ用)。

    ELYZA系モデルは thinking.kakekotoba 等の入れ子で `"x"="y"` や 「…」 といった
    不正JSONを混ぜ、json.loads全体を巻き添えで失敗させることがある。だが必須の
    toku/kokoro自体は正しい"..."値である場合が多いため、ピンポイントで救出する。
    """
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    if m:
        try:
            return json.loads('"' + m.group(1) + '"')  # \uXXXXや\nを正しく復元
        except Exception:
            return m.group(1)
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*[「『]([^」』]*)[」』]', raw)
    if m:
        return m.group(1).strip()
    return None


def extract_json_dict(text: str) -> dict | None:
    """LLMの生テキストから生成結果dictを堅牢に取り出す。失敗時None。

    1) ```json 等のフェンス・HTMLタグを除去
    2) 最初の完結した波括弧ブロックを厳密にjson.loads(Gemini・整形JSONはここで成功)
    3) 失敗時は必須フィールド(toku/kokoro)+hint/persona_commentを正規表現で直接
       サルベージする(全体が壊れていても解き・こころを取りこぼさない)
    """
    if not text:
        return None
    cleaned = re.sub(r"`{1,3}\s*json|`{1,3}", "", text).strip()
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    block = _first_json_block(cleaned)
    candidate = block if block is not None else cleaned

    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj
    except Exception:  # noqa: S110 (2)のサルベージへ委ねる意図的なフォールバック段)
        pass

    toku = _salvage_str_field(cleaned, "toku")
    kokoro = _salvage_str_field(cleaned, "kokoro")
    if toku and kokoro:
        salvaged = {"toku": toku, "kokoro": kokoro}
        hint = _salvage_str_field(cleaned, "hint")
        if hint:
            salvaged["hint"] = hint
        persona_comment = _salvage_str_field(cleaned, "persona_comment")
        if persona_comment:
            salvaged["persona_comment"] = persona_comment
        return salvaged
    return None


def is_valid_nazokake(d: dict | None) -> bool:
    """生成結果が最低限の必須フィールド(toku/kokoro)を満たすか検証する。"""
    if not isinstance(d, dict):
        return False
    return bool(str(d.get("toku", "") or "").strip()) and bool(
        str(d.get("kokoro", "") or "").strip()
    )

"""LLM出力の抽出・検証ユーティリティ ＋ RAG文脈取得（ai_service.py から分離）。

- _first_json_block / _salvage_str_field / _extract_json_dict / _valid_nazokake:
  生テキストから生成結果 dict を堅牢に取り出す（ELYZA の不正/途切れJSON対策）。
- get_rag_context: nazokake_rag_knowledge へのベクトル近傍検索（現状は未結線だが将来の生成文脈用）。
"""

import asyncio
import json
import re

from google import genai
from google.genai.types import EmbedContentConfig
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

from nazokake_core.env_config import get_gemini_api_key


async def get_rag_context(db, odai: str) -> str:
    api_key = get_gemini_api_key()
    if not api_key:
        return "※APIキー未設定"
    try:

        def fetch_vectors():
            client = genai.Client(api_key=api_key)
            res = client.models.embed_content(
                model="gemini-embedding-2",
                contents=odai,
                config=EmbedContentConfig(output_dimensionality=768),
            )
            query_vector = res.embeddings[0].values
            results = (
                db.collection("nazokake_rag_knowledge")
                .find_nearest(
                    vector_field="embedding",
                    query_vector=Vector(query_vector),
                    distance_measure=DistanceMeasure.COSINE,
                    limit=3,
                )
                .stream()
            )
            rag_text = ""
            for i, doc in enumerate(results):
                rag_text += f"[参考例 {i + 1}] お題: {doc.to_dict().get('odai')}\nなぞかけ: {doc.to_dict().get('nazokake')}\n\n"
            return rag_text if rag_text else "※参考データなし"

        return await asyncio.to_thread(fetch_vectors)
    except Exception as e:
        print(f"⚠️ [RAG Error] {e}")
        return "※参考データ取得エラー"


# 改善C: 生成結果の共通パース／検証ユーティリティ
def _first_json_block(text: str):
    """最初の '{' から対応する '}' までの最小完結ブロックを返す（文字列内の括弧は無視）。

    現状の貪欲な r'\\{.*\\}' は「文章 {A} 文章 {B}」で {A}〜{B} 全体を掴んでしまう。
    波括弧の対応をスキャンして最初の1ブロックだけを正確に切り出す。閉じが無ければ残り全部。
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
    return text[start:]  # 閉じ括弧が無い（途中で切れた）場合は残り全部を返す


def _salvage_str_field(raw: str, key: str):
    """raw から "key": "..." / "key": 「...」 の文字列値を1つだけ取り出す（堅牢サルベージ用）。

    ELYZA(elyza:8b) は thinking.kakekotoba 等の入れ子で `"x"="y"` や 「…」 といった
    不正JSONを混ぜ、json.loads 全体を巻き添えで失敗させることがある。だが必須の
    toku/kokoro 自体は正しい "..." 値である場合が多いため、ピンポイントで救出する。
    """
    # 通常のダブルクオート値（バックスラッシュエスケープ対応）
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    if m:
        try:
            return json.loads('"' + m.group(1) + '"')  # \uXXXX や \n を正しく復元
        except Exception:
            return m.group(1)
    # 日本語かぎ括弧で囲まれた値（ELYZA が時々ダブルクオートの代わりに使う）
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*[「『]([^」』]*)[」』]', raw)
    if m:
        return m.group(1).strip()
    return None


def _extract_json_dict(raw: str):
    """生テキストから生成結果 dict を堅牢に取り出す。失敗時 None。

    1) ```json 等のフェンスを除去
    2) 最初の完結した波括弧ブロックを厳密に json.loads（Gemini・整形JSONはここで成功）
    3) 失敗時は必須フィールド(toku/kokoro)＋hint を正規表現で直接サルベージ
       （ELYZA が入れ子で不正JSONを吐いても、肝心の解き・こころを取りこぼさない）
    """
    if not raw:
        return None
    cleaned = re.sub(r"`{1,3}\s*json|`{1,3}", "", raw).strip()
    cleaned = re.sub(r"<[^>]+>", "", cleaned)  # HTMLタグを除去
    block = _first_json_block(cleaned)
    candidate = block if block is not None else cleaned
    # 1) まずは厳密パース
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj
    except Exception:  # noqa: S110 (2)のサルベージへ委ねる意図的なフォールバック段。頻発するため非ログ)
        pass
    # 2) サルベージ: 必須フィールドを直接抜き出す（全体が壊れていても解き/こころを救出）
    toku = _salvage_str_field(cleaned, "toku")
    kokoro = _salvage_str_field(cleaned, "kokoro")
    if toku and kokoro:
        salvaged = {"toku": toku, "kokoro": kokoro}
        hint = _salvage_str_field(cleaned, "hint")
        if hint:
            salvaged["hint"] = hint
        return salvaged
    return None


def _valid_nazokake(d) -> bool:
    """生成結果が最低限の必須フィールド(toku/kokoro)を満たすか検証する。"""
    if not isinstance(d, dict):
        return False
    return bool(str(d.get("toku", "") or "").strip()) and bool(
        str(d.get("kokoro", "") or "").strip()
    )

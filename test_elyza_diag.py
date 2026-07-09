# test_elyza_diag.py
# ELYZA(Ollama) の 500エラー / 出力不正の真因をファクト採取するための診断スクリプト。
# Ollama の OpenAI互換エンドポイント(/v1/chat/completions)を「直接」叩き、3パターンを検証する。
#
#   1. json_mode=True (response_format: {"type":"json_object"})  … 500 になるか？
#   2. json_mode=False                                           … 生テキスト（途切れ/不正記号）
#   3. max_tokens を極端に小さく                                 … 切断/OOM の挙動
#
# ※ このスクリプトは ai_service.py を一切変更しない。生ログの採取のみを行う。
# 実行: python test_elyza_diag.py [お題]

import json
import os
import sys

import httpx
from dotenv import load_dotenv

# Windowsコンソール(cp932)で絵文字・日本語出力時の UnicodeEncodeError を回避
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()

URL = os.environ.get("LLMJP_URL", "http://127.0.0.1:11434/v1/chat/completions")
MODEL = os.environ.get("LLMJP_MODEL", "elyza:8b")
ODAI = sys.argv[1] if len(sys.argv) > 1 else "セキュリティ"

# 本番(_build_gen_prompts)に近い、フラットJSONを要求するプロンプト
SYS_PROMPT = (
    "あなたは天才なぞかけ芸人です。お題に対し、以下のフラットなJSONのみで出力してください。\n"
    '{"associations": ["..."], "kakekotoba": ["..."], "shared_essence": "...", '
    '"surprise_check": "...", "toku": "解き(短い名詞)", "kokoro": "オチの文章"}\n'
    "※挨拶・説明・Markdownは不要。先頭文字は必ず { 。"
)
USER_PROMPT = f"お題「{ODAI}」でなぞかけを作成し、上記JSONで出力。"


def call_ollama(json_mode: bool, max_tokens: int, temperature: float = 0.8):
    """Ollama OpenAI互換エンドポイントを直接叩き、(status, raw_body, parsed_content_or_None) を返す。"""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.9,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
            res = client.post(URL, json=payload, headers={"ngrok-skip-browser-warning": "true"})
        body = res.text
        content = None
        if res.status_code == 200:
            try:
                content = res.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            except Exception:
                content = None
        return res.status_code, body, content
    except Exception as e:
        return -1, f"[EXCEPTION] {type(e).__name__}: {e}", None


def brace_balance(s: str):
    depth, in_str, esc = 0, False, True and False
    bal = True
    for ch in s or "":
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
            if depth < 0:
                bal = False
    return depth, bal


def diagnose(content: str):
    if content is None:
        print("   診断: content なし（200以外 or 例外）")
        return
    print(f"   先頭文字: {content.lstrip()[:1]!r}  / 長さ: {len(content)}")
    if "```" in content:
        print("   ⚠ Markdownコードフェンス(```) 混入")
    for bad in ["「", "」", "『", "』"]:
        if bad in content:
            print(f"   ⚠ 日本語かぎ括弧 {bad} 混入（JSON的に不正の温床）")
            break
    if "=" in content and '"=' in content.replace(" ", ""):
        print('   ⚠ "x"="y" 形式（イコール構文）の疑い')
    depth, bal = brace_balance(content)
    if "{" not in content:
        print("   ⚠ 波括弧 { が無い → JSONを生成していない（自然文）")
    elif depth != 0 or not bal:
        print(f"   ⚠ 波括弧の対応崩れ depth={depth} balanced={bal} → 途切れ/不正の可能性")
    try:
        json.loads(content[content.find("{"): content.rfind("}") + 1])
        print("   ✓ json.loads 成功")
    except Exception as e:
        print(f"   ✗ json.loads 失敗: {e}")


def section(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main():
    print(f"ELYZA 診断  url={URL}  model={MODEL}  お題=「{ODAI}」")

    section("[パターン1] json_mode=True (response_format: json_object), max_tokens=512")
    st, body, content = call_ollama(json_mode=True, max_tokens=512)
    print(f"HTTP status = {st}")
    print(f"raw body (先頭1500字):\n{body[:1500]}")
    diagnose(content)

    section("[パターン2] json_mode=False, max_tokens=512（生テキスト観察）")
    st, body, content = call_ollama(json_mode=False, max_tokens=512)
    print(f"HTTP status = {st}")
    if content is not None:
        print("RAW content (repr):")
        print(repr(content))
        print("\nRAW content (そのまま):")
        print(content)
    else:
        print(f"raw body (先頭1500字):\n{body[:1500]}")
    diagnose(content)

    section("[パターン3] json_mode=False, max_tokens=16（極端に小・切断/OOM確認）")
    st, body, content = call_ollama(json_mode=False, max_tokens=16)
    print(f"HTTP status = {st}")
    if content is not None:
        print("RAW content (repr):")
        print(repr(content))
    else:
        print(f"raw body (先頭1500字):\n{body[:1500]}")
    diagnose(content)

    print("\n診断完了。")


if __name__ == "__main__":
    main()

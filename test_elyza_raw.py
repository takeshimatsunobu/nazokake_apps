# test_elyza_raw.py
# ELYZA(elyza:8b) の「出力が不正（必須フィールド欠落）」バグ調査用の一時検証スクリプト。
#
# 目的:
#   backend/services/ai_service.py の generate_via_llmjp と「完全に同じ」プロンプト構築
#   (_build_gen_prompts) と同じパラメータ (json_mode=False, max_tokens=512, read_timeout=120s)
#   で ELYZA にリクエストを送り、返ってきた【生テキスト(raw)】をそのまま標準出力へ出す。
#   その上で、既存の _extract_json_dict / _valid_nazokake が成否どうなるかを並べて、
#   「なぜ抽出ロジックが失敗するのか」を切り分けられるようにする。
#
# 実行: python test_elyza_raw.py [お題]

import asyncio
import os
import sys
import json
from dotenv import load_dotenv

# Windowsコンソール(cp932)では絵文字・一部日本語の出力で UnicodeEncodeError が出るため UTF-8 に固定
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()  # .env (LLMJP_URL / LLMJP_MODEL 等) を読み込む

import firebase_admin
from firebase_admin import firestore

# 本番と完全に同一のロジックを使うため、ai_service から直接 import する
from backend.services.ai_service import (
    _build_gen_prompts,
    chat_completion_local,
    _extract_json_dict,
    _valid_nazokake,
)

try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app()


async def run():
    odai = sys.argv[1] if len(sys.argv) > 1 else "セキュリティ"

    # generate_via_llmjp と全く同じプロンプト構築・接続先・モデル
    sys_prompt, user_prompt, dyn_temp = await _build_gen_prompts(odai)
    url = os.environ.get("LLMJP_URL", "http://localhost:11434/v1/chat/completions")
    model = os.environ.get("LLMJP_MODEL", "elyza:8b")

    print("=" * 70)
    print(f"🏠 ELYZA 生ログ検証  お題=「{odai}」  model={model}")
    print(f"   url={url}  temp={dyn_temp}  max_tokens=512  json_mode=False")
    print("=" * 70)
    print("\n----- SYSTEM PROMPT -----")
    print(sys_prompt)
    print("\n----- USER PROMPT -----")
    print(user_prompt)

    # generate_via_llmjp と全く同じ呼び出し（json_mode=False, max_tokens=512, read_timeout=120s）
    raw = await chat_completion_local(
        url, sys_prompt, user_prompt, max_tokens=512, temperature=dyn_temp,
        json_mode=False, model=model, read_timeout=120.0,
    )

    print("\n" + "=" * 70)
    print("📥 RAW TEXT（ELYZA が返した生テキストをそのまま出力）")
    print("=" * 70)
    print(repr(raw))  # 不可視文字・改行・前後の空白まで見えるよう repr で
    print("\n----- 同上（人間可読・整形なし） -----")
    print(raw)

    # 既存の抽出ロジックが何を返すかを並べて確認する
    print("\n" + "=" * 70)
    print("🔍 既存ロジックの挙動")
    print("=" * 70)
    cand = _extract_json_dict(raw)
    print(f"_extract_json_dict -> {type(cand).__name__}")
    if cand is not None:
        print(json.dumps(cand, indent=2, ensure_ascii=False))
    print(f"_valid_nazokake    -> {_valid_nazokake(cand)}  "
          f"(toku={cand.get('toku') if isinstance(cand, dict) else None!r}, "
          f"kokoro={cand.get('kokoro') if isinstance(cand, dict) else None!r})")

    # 失敗の典型パターンを自動診断
    print("\n----- 簡易診断 -----")
    if not raw:
        print("・raw が空。接続/タイムアウト/モデル未ロードの可能性。")
    else:
        if "```" in raw:
            print("・Markdownコードフェンス(```)が含まれる。")
        if raw.lstrip()[:1] not in ("{", "["):
            print("・先頭が { や [ でない（挨拶・前置きが混入している可能性）。")
        if "{" not in raw:
            print("・波括弧 { が一切無い → JSONを生成していない（自然文で回答）。")
        else:
            depth = 0
            balanced = True
            for ch in raw:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth < 0:
                        balanced = False
                        break
            if depth != 0 or not balanced:
                print(f"・波括弧の対応が崩れている（depth={depth}）→ "
                      f"max_tokens不足でJSON途中で切れている可能性。")


if __name__ == "__main__":
    asyncio.run(run())

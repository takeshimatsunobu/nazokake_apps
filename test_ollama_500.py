"""一時診断スクリプト: ELYZA(Ollama) の 500 エラー原因を3パターンで切り分ける。
HTTPError でもレスポンスボディ(生のエラー文字列)を必ず .read().decode() で出力する。"""
import urllib.request
import json

MODEL = "elyza:8b"
NATIVE = "http://127.0.0.1:11434/api/generate"
OPENAI = "http://127.0.0.1:11434/v1/chat/completions"


def post(url, payload, label):
    print("\n" + "=" * 70)
    print(f"[{label}] POST {url}")
    print("payload:", json.dumps(payload, ensure_ascii=False))
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read().decode("utf-8", "replace")
            print(f"HTTP {r.status} OK")
            print("body[:800]:", body[:800])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"HTTPError {e.code}")
        print("RAW ERROR BODY:", body)
    except Exception as e:
        print("OTHER ERROR:", type(e).__name__, str(e)[:300])


# テストA: ネイティブAPI /api/generate（真のエラーメッセージを取得）
post(NATIVE, {"model": MODEL, "prompt": "テスト", "stream": False}, "A native /api/generate")

# テストB: /v1/chat/completions に system 無し・単純なユーザープロンプトのみ
post(OPENAI, {
    "model": MODEL,
    "messages": [{"role": "user", "content": "こんにちは"}],
}, "B openai user-only")

# テストC: FastAPI が実際に送るフルペイロード（system あり・max_tokens=512 等）
post(OPENAI, {
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "あなたは前衛的な天才なぞかけ芸人です。JSONで出力してください。"},
        {"role": "user", "content": "お題「猫」でなぞかけを作成し、JSONで出力。"},
    ],
    "max_tokens": 512,
    "temperature": 0.8,
    "top_p": 0.9,
}, "C openai full payload")

print("\n" + "=" * 70)
print("done")

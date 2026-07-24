"""一時スクリプト: ELYZA 8B GGUF を SSL検証無効でDLする（TLS傍受環境の回避）。
中断時は Range で続きから再開。約4.5GB以上が既にあればスキップ。"""
import ssl
import urllib.request
import os
import sys

URL = "https://huggingface.co/mmnga/Llama-3-ELYZA-JP-8B-gguf/resolve/main/Llama-3-ELYZA-JP-8B-Q4_K_M.gguf"
OUT = "Llama-3-ELYZA-JP-8B-Q4_K_M.gguf"
MIN_OK = 4_500_000_000

ctx = ssl._create_unverified_context()
existing = os.path.getsize(OUT) if os.path.exists(OUT) else 0
if existing >= MIN_OK:
    print(f"SKIP: already have {existing/1e9:.2f} GB -> {OUT}", flush=True)
    sys.exit(0)

headers = {"User-Agent": "Mozilla/5.0"}
mode = "wb"
if existing > 0:
    headers["Range"] = f"bytes={existing}-"
    mode = "ab"
    print(f"RESUME from {existing/1e6:.1f} MB", flush=True)

req = urllib.request.Request(URL, headers=headers)
r = urllib.request.urlopen(req, timeout=120, context=ctx)
total = int(r.headers.get("Content-Length", 0)) + existing
print(f"START: target {total/1e9:.2f} GB", flush=True)

done = existing
last = existing
CHUNK = 1024 * 1024
with open(OUT, mode) as f:
    while True:
        buf = r.read(CHUNK)
        if not buf:
            break
        f.write(buf)
        done += len(buf)
        if done - last >= 100 * 1024 * 1024:
            last = done
            pct = (done / total * 100) if total else 0
            print(f"  {done/1e6:9.1f} / {total/1e6:.1f} MB ({pct:5.1f}%)", flush=True)

final = os.path.getsize(OUT)
print(f"DONE: {final/1e9:.3f} GB -> {OUT}", flush=True)
sys.exit(0 if final >= MIN_OK else 1)

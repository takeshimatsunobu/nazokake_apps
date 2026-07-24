import asyncio
import httpx
import time

async def test_elyza():
    url = "http://localhost:11434/v1/chat/completions"
    payload = {
        "model": "elyza:8b",
        "messages": [
            {"role": "system", "content": "あなたはプロの謎掛け師です。お題に対して「〜とかけて、〜ととく。そのこころは、どちらも〜でしょう。」の形式で答えてください。"},
            {"role": "user", "content": "お題：初夏の夕暮れ"}
        ],
        "max_tokens": 256,
        "temperature": 0.8
    }
    
    print(f"🚀 ELYZA (elyza:8b) にリクエストを送信します... (URL: {url})")
    start_time = time.time()
    
    try:
        # 120秒のタイムアウトを設定してローカルへ送信
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
            res = await client.post(url, json=payload)
            res.raise_for_status()
            
            elapsed = time.time() - start_time
            result = res.json()["choices"][0]["message"]["content"]
            
            print(f"\n✅ 成功！ (所要時間: {elapsed:.2f}秒)")
            print("-" * 40)
            print(result)
            print("-" * 40)
            
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n❌ エラー発生 (所要時間: {elapsed:.2f}秒)")
        print(f"詳細: {e}")

asyncio.run(test_elyza())

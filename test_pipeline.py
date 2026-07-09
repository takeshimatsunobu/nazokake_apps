import asyncio
from dotenv import load_dotenv
load_dotenv() # .envを読み込むだけ

import firebase_admin
from firebase_admin import firestore
from backend.services.ai_service import generate_nazokake

try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app()

async def run_test():
    db = firestore.client()
    db.collection("system_configs").document("ai_settings").set({
        "model_name": "us-local-gemma"
    }, merge=True)

    odai = "セキュリティ"
    print(f"=========================================")
    print(f"🚀 テスト開始: お題「{odai}」をシステムに投げます...")
    print(f"=========================================\n")
    
    result = await generate_nazokake(odai)
    
    print("\n=========================================")
    print("🎯 最終出力結果 (JSON):")
    print("=========================================")
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    asyncio.run(run_test())

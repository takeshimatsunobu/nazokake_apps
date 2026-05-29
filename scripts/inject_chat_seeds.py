import os
import sys
import json
import time
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore

def inject_seeds():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    data_path = current_dir / "data" / "golden_seeds_batch.json"

    if not data_path.exists():
        print(f"⚠️ {data_path} が見つかりません。")
        return

    # Firebase初期化（冪等性の担保）
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()

    with open(data_path, 'r', encoding='utf-8') as f:
        seeds = json.load(f)

    print(f"🚀 {len(seeds)}件の高品質なぞかけの注入を開始します...")
    print("⚠️ Gemini APIのRate Limit（429エラー）とワーカーの暴走を防ぐため、1件あたり15秒の意図的なディレイを入れます。")

    for i, seed in enumerate(seeds):
        odai = seed.get("A_TITLE")
        text = seed.get("nazokake_text")

        doc_ref = db.collection("nazokake_items").document()
        doc_ref.set({
            "A_TITLE": odai,
            "nazokake_text": text,
            "status": 0,  # Eventarcとワーカーを起動するトリガー
            "author": "Takeshi_Gemini_Brainstorm", # チャットからの注入であることを明記
            "is_golden": False, # まだAIの11軸評価を受けていないため
            "scores": {},
            "user_evaluations": [],
            "created_at": firestore.SERVER_TIMESTAMP
        })
        
        print(f"[{i+1}/{len(seeds)}] 💉 注入完了 (status: 0): お題「{odai}」 -> ワーカーへ起動シグナル発火！")

        if i < len(seeds) - 1:
            print("   ⏳ クラウドの評価完了を待機中... (15秒)")
            time.sleep(15)

    print("🎉 全件の注入が完了しました！バックエンドで順次11軸評価が進んでいます。")

if __name__ == '__main__':
    inject_seeds()

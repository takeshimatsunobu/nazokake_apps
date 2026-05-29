import os
import json
import traceback
from typing import Dict, Any, Optional
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from sentence_transformers import SentenceTransformer

# 💡 修正ポイント：ローカルとクラウド(Cloud Run)の両方で鍵を見つけられるようにする
current_dir = Path.cwd()
key_path = current_dir / "serviceAccountKey.json" # 優先: Cloud Runのパス
if not key_path.exists():
    key_path = current_dir / "backend" / "serviceAccountKey.json" # 代替: ローカルPCのパス

if not firebase_admin._apps:
    if key_path.exists():
        cred = credentials.Certificate(str(key_path))
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.initialize_app()
db = firestore.client()

print("🚀 [RAG Init] GLuCoSE v2 モデルをロード中...")
encoder_model = SentenceTransformer('pkshatech/GLuCoSE-base-ja-v2', trust_remote_code=True)
print("✅ [RAG Init] モデルロード完了")

def get_rag_context(odai: str) -> str:
    try:
        query_vector = encoder_model.encode([odai])[0].tolist()
        collection_ref = db.collection("nazokake_rag_knowledge")
        results = collection_ref.find_nearest(
            vector_field="embedding",
            query_vector=Vector(query_vector),
            distance_measure=DistanceMeasure.COSINE,
            limit=3
        ).stream()

        rag_text = ""
        count = 0
        for doc in results:
            data = doc.to_dict()
            count += 1
            rag_text += f"[参考例 {count}] お題: {data.get('odai')}\nなぞかけ: {data.get('nazokake')}\n\n"
            
        if count == 0:
            return "※参考データなし"
        return rag_text
    except Exception as e:
        print(f"⚠️ [RAG Error] ベクトル検索中にエラー発生: {e}")
        return "※参考データ取得エラー"

def run_gemini_evaluation(item_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("環境変数 GEMINI_API_KEY が設定されていません")
            
        client = genai.Client(api_key=api_key)
        odai = data.get("A_TITLE", "")
        nazokake_text = data.get("nazokake_text", "")
        
        if not odai or not nazokake_text:
            raise ValueError("評価に必要なデータが不足しています")

        print(f"🔍 [Eval] ID: {item_id} (お題: {odai}) の評価を開始...")
        rag_context = get_rag_context(odai)
        print(f"📚 [RAG Info] 取得した過去の傑作コンテキスト:\n{rag_context}")

        prompt = f'''
あなたは、なぞかけの美しさと面白さを極めた「最高峰の審査員（AI落語家）」です。
以下の「評価対象のなぞかけ」を、11の学術的指標に基づき、0.0〜1.0の範囲で厳密にスコアリングしてください。

【評価の参考データ（過去の似たお題の傑作）】
以下のなぞかけは、過去に人間が高く評価した「お手本（正解）」のデータです。
これを基準（アンカー）として、今回の作品の「意味の遠さ」や「オチの美しさ」を相対的に比較・採点してください。
---
{rag_context}
---

【評価対象のなぞかけ】
お題: {odai}
作品: {nazokake_text}

【出力ルール】
必ず以下のJSON形式（スキーマ）のみを出力してください。Markdownの装飾（`json）は絶対に含めないでください。

{{
  "reasoning": "全体の講評や、参考データと比較した際の優れた点・劣る点を簡潔に記述してください",
  "S_sur": 0.0,
  "S_nat": 0.0,
  "S_tech": 0.0,
  "S_emo": 0.0,
  "S_rhy": 0.0,
  "S_sensory": 0.0,
  "S_visual": 0.0,
  "S_ontology": 0.0,
  "S_cultural": 0.0,
  "S_cm": 0.0,
  "S_prosody": 0.0,
  "S_total": 0.0
}}
'''

        # 正しいモデル名
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json"
            )
        )
        
        result_text = response.text.strip()
        if result_text.startswith("`json"):
            result_text = result_text[7:]
        if result_text.endswith("`"):
            result_text = result_text[:-3]
            
        evaluation_result = json.loads(result_text)
        print(f"✅ [Eval Success] ID: {item_id} の評価が完了しました")
        return evaluation_result

    except Exception as e:
        print(f"❌ [Eval Error] ID: {item_id} の評価中にエラー: {e}")
        traceback.print_exc()
        return None

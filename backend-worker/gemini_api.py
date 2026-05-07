import google.generativeai as genai
import os
import json
import logging

logger = logging.getLogger(__name__)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

def evaluate_with_gemini(data: dict) -> dict:
    """Gemini 2.5 Flashを呼び出し、11軸スコアのJSONを返す"""
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    # プロンプトの組み立て（システムプロンプト等は適宜拡張してください）
    prompt = f"""
    以下のなぞかけを11軸で評価し、JSON形式の数値(0.0〜1.0)のみを返してください。
    お題A: {data.get('A_TITLE')}
    お題B: {data.get('B_TITLE')}
    解の読み: {data.get('C_READING')}
    なぞかけ: {data.get('nazokake_text')}
    """
    
    # 強制JSONモード (status: 9の主な原因だったパースエラーを根絶)
    response = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json"
        )
    )
    
    return json.loads(response.text)
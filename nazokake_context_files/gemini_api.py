import os
import json
import logging
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

logger = logging.getLogger(__name__)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
MODEL_NAME = "gemini-2.5-flash"

async def evaluate_nazokake(doc_data: dict) -> dict:
    response_schema = {
        "type": "object",
        "properties": {
            "S_sur": {"type": "number"}, "S_nat": {"type": "number"},
            "S_tech": {"type": "number"}, "S_emo": {"type": "number"},
            "S_rhy": {"type": "number"}, "S_sensory": {"type": "number"},
            "S_visual": {"type": "number"}, "S_ontology": {"type": "number"},
            "S_cultural": {"type": "number"}, "S_cm": {"type": "number"},
            "S_prosody": {"type": "number"}
        },
        "required": [
            "S_sur", "S_nat", "S_tech", "S_emo", "S_rhy", "S_sensory", 
            "S_visual", "S_ontology", "S_cultural", "S_cm", "S_prosody"
        ]
    }

    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=response_schema
        )
    )

    prompt = f"""
    以下のなぞかけを11の評価軸で0.0から1.0の範囲でスコアリングしてください。
    【お題】: {doc_data.get('A_TITLE')} とかけて {doc_data.get('B_TITLE')} と解く
    【その心は】: どちらも {doc_data.get('C_READING')} ({doc_data.get('A_CONTEXT_DETAIL')})
    【完成文章】: {doc_data.get('nazokake_text')}
    """

    try:
        response = await model.generate_content_async(prompt)
        return json.loads(response.text)
    except ResourceExhausted as e:
        logger.error("Gemini APIのレート制限(429)に到達しました。")
        raise e
    except Exception as e:
        logger.error(f"Gemini API呼び出し中に予期せぬエラー: {e}")
        raise e

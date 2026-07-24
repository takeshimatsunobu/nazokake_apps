import os

"""11軸評価エンジン（ai_service.py から分離）。

A-1 ルーブリック文面 ＋ B-1 構造化出力スキーマ。絶対評価ブラインドテスト。
他サービスに依存しない自己完結モジュール（自前で JSON をパースする）。
"""
import asyncio
import json

from firebase_admin import firestore
from google import genai
from google.genai.types import GenerateContentConfig

from nazokake_core.schemas import EvaluationOutput

AXES = [
    "S_nat",
    "S_tech",
    "S_rhy",
    "S_prosody",
    "S_sur",
    "S_emo",
    "S_cultural",
    "S_visual",
    "S_sensory",
    "S_cm",
    "S_ontology",
]

_AXIS_DESC = {
    "S_nat": "自然さ: 日本語として自然に成立しているか (0.0-1.0)",
    "S_tech": "技巧性: 同音異義語・掛詞などの言葉遊びの精巧さ (0.0-1.0)",
    "S_rhy": "リズム: 音読時の心地よさ・七五調など (0.0-1.0)",
    "S_prosody": "韻律: 母音の響き・押韻など音響的な美しさ (0.0-1.0)",
    "S_sur": "意外性: お題と解きの距離・結びつきの意外さ (0.0-1.0)",
    "S_emo": "論理/納得感: 種明かしの論理的納得度・アハ体験 (0.0-1.0)",
    "S_cultural": "文化的背景: 文化・常識・共通認識の活用 (0.0-1.0)",
    "S_visual": "視覚的喚起力: 鮮明な映像が浮かぶか (0.0-1.0)",
    "S_sensory": "感覚的表現: 視覚以外の五感への訴求 (0.0-1.0)",
    "S_cm": "クロスモーダル: 異なる感覚領域の比喩的交差 (0.0-1.0)",
    "S_ontology": "存在論的深み: 本質・存在意義の共通点を突くか (0.0-1.0)",
}

EVAL_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "scores": {
            "type": "OBJECT",
            "description": "11軸の数値評価。各値は0.00〜1.00の小数。",
            "properties": {
                k: {
                    "type": "NUMBER",
                    "description": _AXIS_DESC[k],
                    "minimum": 0.0,
                    "maximum": 1.0,
                }
                for k in AXES
            },
            "required": AXES,
            "propertyOrdering": AXES,
        },
        "axis_comments": {
            "type": "OBJECT",
            "description": "11軸それぞれの採点理由（各1〜2文の短い所見）。",
            "properties": {
                k: {"type": "STRING", "description": f"{_AXIS_DESC[k]} の採点理由"}
                for k in AXES
            },
            "required": AXES,
            "propertyOrdering": AXES,
        },
        "overall": {
            "type": "STRING",
            "description": "作品全体の総評。長所・短所、最も光る軸と弱い軸に言及する学術的講評。",
        },
    },
    "required": ["scores", "axis_comments", "overall"],
    "propertyOrdering": ["scores", "axis_comments", "overall"],
}

# 評価用システムプロンプト（A-1）。{odai} / {nazokake_text} を実行時に差し込む。
EVAL_RUBRIC_TEMPLATE = """あなたは「謎掛け学術振興会」の主席分析官AIです。
認知科学・言語学・詩学の知見に基づき、提示された「なぞかけ作品」を11の評価軸で厳密に採点します。

【採点の大原則】
1. これは「絶対評価」です。他の作品やデータベースとの比較ではなく、下記の各軸の定義そのものに基づいて評価してください。
2. 各スコアは 0.00〜1.00 の小数です。0〜10 や 0〜100 のスケールは絶対に使わないでください。
3. 安易に 0.5 を多用せず、定義に基づいて軸ごとに明確な差をつけてください。該当しなければ大胆に低く、傑出していれば大胆に高く採点します。
4. 採点は作品（お題・解き・心）そのものに基づいて行い、作者の意図や言い訳は考慮しません。
5. 各軸の所見（axis_comments）は、その軸の定義に照らした採点理由を1〜2文で簡潔に述べてください。
6. 総評（overall）は、作品全体の長所と短所、最も光る軸と弱い軸に言及する学術的講評。"""

# Phase 4 Lv.2: フィードバック乖離分析(feedback_analyzer.generate_correction_prompt)から
# 動的に更新される自己評価の補正指示。既定は空文字(既存挙動を変えない)。
_DYNAMIC_CORRECTION_PROMPT = ""


def update_dynamic_correction_prompt(new_prompt: str) -> None:
    """_DYNAMIC_CORRECTION_PROMPT を外部(Webhookエンドポイント等)から安全に更新する。"""
    global _DYNAMIC_CORRECTION_PROMPT
    _DYNAMIC_CORRECTION_PROMPT = new_prompt


async def _log_evaluation_cost(
    service_type: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    execution_time_sec: float = 0.0,
) -> None:
    """評価コストをsystem_costsへ非同期記録する(失敗しても評価処理自体は継続する)。"""
    try:
        from nazokake_core.cost_calculator import async_log_system_cost

        db = firestore.client()
        await async_log_system_cost(
            db,
            service_type=service_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            execution_time_sec=execution_time_sec,
        )
    except Exception as e:
        print(f"⚠️ コストログ記録に失敗しました(評価処理には影響なし): {e}")


async def run_evaluation(odai: str, nazokake_text: str) -> dict:
    """Gemini APIで11軸評価を実行し、nazokake_core.schemas.EvaluationOutputで
    データ契約(scores/axis_comments/overallの形状)を検証した上でs_totalを添えて返す。
    """
    model_name = os.environ.get("EVALUATOR_MODEL_NAME", "gemini-3.5-flash")
    prompt = f"{EVAL_RUBRIC_TEMPLATE}\n\n【評価対象】\nお題: {odai}\nなぞかけ全文:\n{nazokake_text}"
    if _DYNAMIC_CORRECTION_PROMPT:
        prompt += f"\n\n{_DYNAMIC_CORRECTION_PROMPT}"

    def _call():
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        return client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=EVAL_SCHEMA,
                temperature=0.1,
            ),
        )

    start_time = asyncio.get_running_loop().time()
    response = await asyncio.to_thread(_call)
    elapsed = asyncio.get_running_loop().time() - start_time

    usage = getattr(response, "usage_metadata", None)
    await _log_evaluation_cost(
        model_name,
        input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
        output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        execution_time_sec=elapsed,
    )

    data = json.loads(response.text)

    validated = EvaluationOutput.model_validate(data)
    scores = validated.scores
    values = [float(scores.get(k, 0.5)) for k in AXES]
    s_total = round((sum(values) / len(values)) * 5.0, 4) if values else 0.0

    return {
        "scores": scores,
        "s_total": s_total,
        "axis_comments": validated.axis_comments,
        "overall": validated.overall,
    }
